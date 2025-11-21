from flask import Flask, render_template, request, redirect, url_for, flash ,session
import mysql.connector
from datetime import date , datetime
import csv
from flask import send_file, make_response
from io import StringIO
from functools import wraps
import mysql.connector
from mysql.connector import Error
from mysql.connector import pooling
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "rbmi_secret_key"

dbconfig = {
    "host": "mydb-india.c5mmu4oakvas.ap-south-1.rds.amazonaws.com",
    "user": "admin",
    "password": "38093809Rr",
    "database": "rbmi_inventory",
    "auth_plugin": "mysql_native_password"
}

connection_pool = pooling.MySQLConnectionPool(
    pool_name="rbmi_pool",
    pool_size=10,   # max 10 concurrent connections
    **dbconfig
)

def get_connection():
    try:
        return connection_pool.get_connection()
    except Error as e:
        print(f"Database connection failed: {e}")
        return None




@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = request.form['role']
        password = request.form['password']

        conn = get_connection()
        if conn is None:
            flash("Database connection failed. Please try again later.", "danger")
            return redirect(url_for('login'))

        cursor = conn.cursor(dictionary=True)


        # Fetch user by role
        cursor.execute("SELECT username, password, role FROM users WHERE role=%s", (role,))
        user = cursor.fetchone()

        cursor.close()
        conn.close()

        if user and user['password'] == password:
            # Set session
            session['username'] = user['username']  # auto username = role's username
            session['role'] = user['role']
            
            return redirect(url_for(f"{user['role']}_dashboard"))  # role-based dashboard redirect
        else:
            flash("Invalid credentials!", "danger")
            return redirect(url_for("login"))

    return render_template("login.html")

# --------- Login required decorator ----------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            flash("Please login first.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --------- Role required decorator ----------
def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'role' not in session:
                flash("Please login first.", "danger")
                return redirect(url_for('login'))
            if session['role'] not in allowed_roles:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@app.route("/add_item_master", methods=["GET", "POST"])
@login_required
@role_required(['manager'])
def add_item_master():
    conn = get_connection()
    if conn is None:
        flash("Database connection failed. Please try again later.", "danger")
        return redirect(url_for('login'))

    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        item_name = request.form['item_name']
        unit = request.form['unit']

        cursor.execute(
            "INSERT INTO items_master (item_name, unit) VALUES (%s, %s)",
            (item_name, unit)
        )
        conn.commit()
        flash("Item Added Successfully!", "success")
        return redirect(url_for('add_item_master'))

    cursor.execute("SELECT * FROM items_master ORDER BY item_id asc")
    items = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("add_item_master.html", items=items)
#--------------order recived--------------------------
@app.route("/order_received", methods=["GET", "POST"])
@login_required
@role_required(['manager'])
def order_received():
    conn = get_connection()
    if conn is None:
        flash("Database connection failed. Please try again later.", "danger")
        return redirect(url_for('login'))

    cursor = conn.cursor(dictionary=True)

    # POST save order
    if request.method == "POST":
        vendor = request.form['vendor_name']
        item_id = request.form['item_id']
        unit = request.form['unit']
        total = request.form['total_qty']
        mess = request.form['mess_qty']
        canteen = request.form['canteen_qty']
        price = request.form['price']

        # Insert into orders table
        cursor.execute("""
            INSERT INTO orders (vendor_name, item_id, unit, total_qty, mess_qty, canteen_qty, price)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (vendor, item_id, unit, total, mess, canteen, price))

        # Update mess stock
        cursor.execute("""
            INSERT INTO mess_stock (item_id, quantity)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)
        """, (item_id, mess))

        # Update canteen stock
        cursor.execute("""
            INSERT INTO canteen_stock (item_id, quantity)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)
        """, (item_id, canteen))

        conn.commit()
        flash("Order Saved & Stocks Updated!", "success")
        return redirect(url_for('order_received'))

    # Load items for dropdown
    cursor.execute("SELECT * FROM items_master ORDER BY item_name ASC")
    items = cursor.fetchall()

    # Load all orders
    cursor.execute("""
        SELECT o.*, i.item_name 
        FROM orders o 
        JOIN items_master i ON o.item_id = i.item_id
        ORDER BY o.id DESC
    """)
    orders = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("order_received.html", items=items, orders=orders)
#------------------stock dashboarrd-------------
@app.route("/manager_dashboard")
@login_required
@role_required(['manager'])
def manager_dashboard():
    conn = get_connection()
    if conn is None:
        flash("Database connection failed. Please try again later.", "danger")
        return redirect(url_for('login'))

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT 
            im.item_id,
            im.item_name,
            im.unit,
            COALESCE(ms.quantity, 0) AS mess_qty,
            COALESCE(cs.quantity, 0) AS canteen_qty,
            (COALESCE(ms.quantity, 0) + COALESCE(cs.quantity, 0)) AS total_qty
        FROM items_master im
        LEFT JOIN mess_stock ms ON im.item_id = ms.item_id
        LEFT JOIN canteen_stock cs ON im.item_id = cs.item_id
        ORDER BY im.item_name ASC
    """)
    stock = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("manager_dashboard.html", stock=stock)

# ------------------ Mess Dashboard ------------------
@app.route("/mess_dashboard", methods=["GET", "POST"])
@login_required
@role_required(['mess', 'manager'])
def mess_dashboard():
    conn = get_connection()
    if conn is None:
        flash("Database connection failed. Please try again later.", "danger")
        return redirect(url_for('login'))

    cursor = conn.cursor(dictionary=True)

    # POST request when using an item
    if request.method == "POST":
        item_name = request.form['item_name']
        quantity_used = float(request.form['quantity'])
        source = request.form['source']  # "mess"

        # Get item_id from name
        cursor.execute("SELECT item_id FROM items_master WHERE item_name=%s", (item_name,))
        row = cursor.fetchone()
        if not row:
            flash(f"Item '{item_name}' not found!", "danger")
            return redirect(url_for('mess_dashboard'))
        item_id = row['item_id']

        # Check current mess stock
        cursor.execute("SELECT quantity FROM mess_stock WHERE item_id=%s", (item_id,))
        stock_row = cursor.fetchone()
        if not stock_row or stock_row['quantity'] < quantity_used:
            flash(f"Not enough stock for '{item_name}'!", "danger")
            return redirect(url_for('mess_dashboard'))

        # Reduce mess stock
        cursor.execute("""
            UPDATE mess_stock 
            SET quantity = quantity - %s
            WHERE item_id=%s
        """, (quantity_used, item_id))

        # Insert into mess_usage
        cursor.execute("""
            INSERT INTO mess_usage (item_id, quantity_used, used_date)
            VALUES (%s, %s, %s)
        """, (item_id, quantity_used, date.today()))

        conn.commit()
        flash(f"Used {quantity_used} units of {item_name}.", "success")
        return redirect(url_for('mess_dashboard'))

    # GET request: show current stock and today's usage
    cursor.execute("""
        SELECT im.item_id, im.item_name, COALESCE(ms.quantity,0) AS quantity, im.unit
        FROM items_master im
        LEFT JOIN mess_stock ms ON im.item_id = ms.item_id
        ORDER BY im.item_name ASC
    """)
    stock = cursor.fetchall()

    # Optional: filter by selected date
    selected_date = request.args.get('selected_date', date.today().isoformat())
    cursor.execute("""
        SELECT u.quantity_used, i.item_name, u.used_date
        FROM mess_usage u
        JOIN items_master i ON u.item_id = i.item_id
        WHERE u.used_date=%s
        ORDER BY u.id DESC
    """, (selected_date,))
    usage = cursor.fetchall()

    cursor.close()
    conn.close()

    filters = {"selected_date": selected_date}
    return render_template("mess_dashboard.html", stock=stock, usage=usage, filters=filters)


# ------------------ Canteen Dashboard ------------------
@app.route("/canteen_dashboard", methods=["GET", "POST"])
@login_required
@role_required(['canteen', 'manager'])
def canteen_dashboard():
    conn = get_connection()
    if conn is None:
        flash("Database connection failed. Please try again later.", "danger")
        return redirect(url_for('login'))

    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        item_name = request.form['item_name']
        quantity_used = float(request.form['quantity'])
        source = request.form['source']  # "canteen"

        # Get item_id
        cursor.execute("SELECT item_id FROM items_master WHERE item_name=%s", (item_name,))
        row = cursor.fetchone()
        if not row:
            flash(f"Item '{item_name}' not found!", "danger")
            return redirect(url_for('canteen_dashboard'))
        item_id = row['item_id']

        # Check current canteen stock
        cursor.execute("SELECT quantity FROM canteen_stock WHERE item_id=%s", (item_id,))
        stock_row = cursor.fetchone()
        if not stock_row or stock_row['quantity'] < quantity_used:
            flash(f"Not enough stock for '{item_name}'!", "danger")
            return redirect(url_for('canteen_dashboard'))

        # Reduce canteen stock
        cursor.execute("""
            UPDATE canteen_stock 
            SET quantity = quantity - %s
            WHERE item_id=%s
        """, (quantity_used, item_id))

        # Insert into canteen_usage
        cursor.execute("""
            INSERT INTO canteen_usage (item_id, quantity_used, used_date)
            VALUES (%s, %s, %s)
        """, (item_id, quantity_used, date.today()))

        conn.commit()
        flash(f"Used {quantity_used} units of {item_name}.", "success")
        return redirect(url_for('canteen_dashboard'))

    # GET request
    cursor.execute("""
        SELECT im.item_id, im.item_name, COALESCE(cs.quantity,0) AS quantity, im.unit
        FROM items_master im
        LEFT JOIN canteen_stock cs ON im.item_id = cs.item_id
        ORDER BY im.item_name ASC
    """)
    stock = cursor.fetchall()

    selected_date = request.args.get('selected_date', date.today().isoformat())
    cursor.execute("""
        SELECT u.quantity_used, i.item_name, u.used_date
        FROM canteen_usage u
        JOIN items_master i ON u.item_id = i.item_id
        WHERE u.used_date=%s
        ORDER BY u.id DESC
    """, (selected_date,))
    usage = cursor.fetchall()

    cursor.close()
    conn.close()

    filters = {"selected_date": selected_date}
    return render_template("canteen_dashboard.html", stock=stock, usage=usage, filters=filters)

@app.route("/usage_report", methods=["GET", "POST"])
def usage_report():
    conn = get_connection()
    if conn is None:
        flash("Database connection failed. Please try again later.", "danger")
        return redirect(url_for('login'))

    cursor = conn.cursor(dictionary=True)

    usage_type = request.form.get('usage_type', 'both')  # mess / canteen / both
    from_date = request.form.get('from_date', date.today().isoformat())
    to_date = request.form.get('to_date', date.today().isoformat())
    export_csv = request.form.get('export_csv', None)

    query_list = []
    params = []

    if usage_type in ['mess', 'both']:
        query_list.append("""
            SELECT 'Mess' AS source, i.item_name, u.quantity_used, u.used_date
            FROM mess_usage u
            JOIN items_master i ON u.item_id = i.item_id
            WHERE u.used_date BETWEEN %s AND %s
        """)
        params.extend([from_date, to_date])

    if usage_type in ['canteen', 'both']:
        query_list.append("""
            SELECT 'Canteen' AS source, i.item_name, u.quantity_used, u.used_date
            FROM canteen_usage u
            JOIN items_master i ON u.item_id = i.item_id
            WHERE u.used_date BETWEEN %s AND %s
        """)
        params.extend([from_date, to_date])

    # Combine queries if both
    if len(query_list) == 2:
        final_query = f"{query_list[0]} UNION ALL {query_list[1]} ORDER BY used_date DESC"
    else:
        final_query = query_list[0] + " ORDER BY used_date DESC"

    cursor.execute(final_query, params)
    results = cursor.fetchall()

    # ---------------- Item-wise summary ----------------
    summary = []

    if usage_type in ['mess', 'canteen']:
        table = 'mess_usage' if usage_type == 'mess' else 'canteen_usage'
        source_name = usage_type.capitalize()
        cursor.execute(f"""
            SELECT i.item_name, SUM(u.quantity_used) AS total_used, %s AS source
            FROM {table} u
            JOIN items_master i ON u.item_id = i.item_id
            WHERE u.used_date BETWEEN %s AND %s
            GROUP BY i.item_name
        """, (source_name, from_date, to_date))
        summary = cursor.fetchall()

    elif usage_type == 'both':
            # Combine Mess + Canteen quantities item-wise
        cursor.execute(f"""
            SELECT i.item_name, SUM(u.quantity_used) AS total_used, 'Both' AS source
            FROM (
                SELECT item_id, quantity_used FROM mess_usage WHERE used_date BETWEEN %s AND %s
                UNION ALL
                SELECT item_id, quantity_used FROM canteen_usage WHERE used_date BETWEEN %s AND %s
            ) u
            JOIN items_master i ON u.item_id = i.item_id
            GROUP BY i.item_name
        """, (from_date, to_date, from_date, to_date))
        summary = cursor.fetchall()


    if export_csv:
        si = StringIO()
        cw = csv.writer(si)
    
    # Detailed rows
        cw.writerow(['Source', 'Item Name', 'Quantity Used', 'Date'])
        for row in results:
            cw.writerow([row['source'], row['item_name'], row['quantity_used'], row['used_date']])
    
    # Empty row as separator
        cw.writerow([])
    
    # Summary rows
        cw.writerow(['Summary'])
        cw.writerow(['Item Name', 'Total Quantity Used', 'Source'])
        for row in summary:
            cw.writerow([row['item_name'], row['total_used'], row['source']])
    
        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = f"attachment; filename=usage_report_{from_date}_to_{to_date}.csv"
        output.headers["Content-type"] = "text/csv"
        return output


    cursor.close()
    conn.close()

    return render_template("usage_report.html",
                       results=results,
                       summary=summary,
                       usage_type=usage_type,
                       from_date=from_date,
                       to_date=to_date)

@app.route("/export_stock_csv")
def export_stock_csv():
    conn = get_connection()
    if conn is None:
        flash("Database connection failed. Please try again later.", "danger")
        return redirect(url_for('login'))

    cursor = conn.cursor(dictionary=True)

    # Get current stock
    cursor.execute("""
        SELECT 
            im.item_id,
            im.item_name,
            im.unit,
            COALESCE(ms.quantity, 0) AS mess_qty,
            COALESCE(cs.quantity, 0) AS canteen_qty,
            (COALESCE(ms.quantity, 0) + COALESCE(cs.quantity, 0)) AS total_qty
        FROM items_master im
        LEFT JOIN mess_stock ms ON im.item_id = ms.item_id
        LEFT JOIN canteen_stock cs ON im.item_id = cs.item_id
        ORDER BY im.item_name ASC
    """)
    stock = cursor.fetchall()

    # CSV writing
    si = StringIO()
    cw = csv.writer(si)

    # Header
    cw.writerow(['Item ID', 'Item Name', 'Mess Stock', 'Canteen Stock', 'Total Stock', 'Unit'])

    # Data rows
    for s in stock:
        cw.writerow([s['item_id'], s['item_name'], s['mess_qty'], s['canteen_qty'], s['total_qty'], s['unit']])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=stock_report.csv"
    output.headers["Content-type"] = "text/csv"

    cursor.close()
    conn.close()
    return output


@app.route("/logout")
def logout():
    # Session clear kar do
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------- Change Password ----------------
@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    if 'username' not in session:
        flash("Please login first.", "danger")
        return redirect(url_for('login'))

    conn = get_connection()
    if conn is None:
        flash("Database connection failed. Please try again later.", "danger")
        return redirect(url_for('login'))

    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        old_password = request.form['old_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        username = session['username']

        # Fetch user's current password from DB
        cursor.execute("SELECT password FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()
        if not user:
            flash("User not found!", "danger")
            return redirect(url_for('change_password'))

        # Check old password
        if user['password'] != old_password:
            flash("Old password is incorrect!", "danger")
            return redirect(url_for('change_password'))

        # Check new password match
        if new_password != confirm_password:
            flash("New password and confirm password do not match!", "danger")
            return redirect(url_for('change_password'))

        # Update password in DB
        cursor.execute("UPDATE users SET password=%s WHERE username=%s", (new_password, username))
        conn.commit()
        flash("Password updated successfully!", "success")
        return redirect(url_for('change_password'))

    cursor.close()
    conn.close()
    return render_template("change_password.html")



if __name__ == "__main__":
    app.run(debug=False,host='0.0.0.0' , port=5151)
