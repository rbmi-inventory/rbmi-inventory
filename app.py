# app.py
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    make_response,
)
from datetime import date,datetime,timedelta
from functools import wraps
from io import StringIO
import csv

import mysql.connector
from mysql.connector import pooling, Error

app = Flask(__name__)
app.secret_key = "rbmi_secret_key"

# ================== DB CONFIG ==================
dbconfig = {
    "host": "database-1.cz84qw6g2wnj.ap-south-1.rds.amazonaws.com",
    "user": "admin",
    "password": "rbmi2025",
    "database": "rbmi_inventory",
    "auth_plugin": "mysql_native_password",
    "connection_timeout": 5,  # fast fail if DB not responding
}

# Single lightweight pool
connection_pool = pooling.MySQLConnectionPool(
    pool_name="rbmi_pool",
    pool_size=10,          # 3 users ke liye more than enough
    pool_reset_session=True,
    **dbconfig
)


def get_connection():
    """Fast & safe connection getter."""
    try:
        conn = connection_pool.get_connection()
        # ensure connection is alive; reconnect if dropped
        conn.ping(reconnect=True)
        return conn
    except Exception as e:
        print("DB CONNECTION ERROR:", e)
        return None


# ================== AUTH DECORATORS ==================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            flash("Please login first.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            role = session.get("role")
            if role is None:
                flash("Please login first.", "danger")
                return redirect(url_for("login"))
            if role not in allowed_roles:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ================== LOGIN ==================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role")
        password = request.form.get("password")

        conn = get_connection()
        if not conn:
            flash("Database connection failed. Please try again later.", "danger")
            return redirect(url_for("login"))

        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT username, password, role FROM users WHERE role=%s", (role,)
            )
            user = cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

        if user and user["password"] == password:
            session["username"] = user["username"]
            session["role"] = user["role"]
            try:
                return redirect(url_for(f"{user['role']}_dashboard"))
            except Exception:
                return redirect(url_for("manager_dashboard"))
        else:
            flash("Invalid credentials!", "danger")
            return redirect(url_for("login"))

    return render_template("login.html")


# ================== ADD ITEM MASTER ==================
@app.route("/add_item_master", methods=["GET", "POST"])
@login_required
@role_required(["manager"])
def add_item_master():
    conn = get_connection()
    if not conn:
        flash("Database connection failed.", "danger")
        return redirect(url_for("login"))

    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "POST":
            item_name = request.form["item_name"]
            unit = request.form["unit"]

            cursor.execute(
                "INSERT INTO items_master (item_name, unit) VALUES (%s, %s)",
                (item_name, unit),
            )
            conn.commit()
            flash("Item Added Successfully!", "success")
            return redirect(url_for("add_item_master"))

        cursor.execute("SELECT * FROM items_master ORDER BY item_id ASC")
        items = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template("add_item_master.html", items=items)


# ================== ORDER RECEIVED ==================
@app.route("/order_received", methods=["GET", "POST"])
@login_required
@role_required(["manager"])
def order_received():
    conn = get_connection()
    if not conn:
        flash("Database connection failed.", "danger")
        return redirect(url_for("login"))

    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "POST":
            vendor = request.form["vendor_name"]
            item_id = request.form["item_id"]
            unit = request.form["unit"]
            total = float(request.form["total_qty"] or 0)
            mess = float(request.form["mess_qty"] or 0)
            canteen = float(request.form["canteen_qty"] or 0)
            purchase_amount = float(request.form["price"] or 0)   # total amount

            # Insert order
            cursor.execute(
                """
                INSERT INTO orders (vendor_name, item_id, unit, total_qty, mess_qty, canteen_qty, price)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (vendor, item_id, unit, total, mess, canteen, purchase_amount),
            )

            # Mess stock update
            cursor.execute(
                """
                INSERT INTO mess_stock (item_id, quantity)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)
                """,
                (item_id, mess),
            )

            # Canteen stock update
            cursor.execute(
                """
                INSERT INTO canteen_stock (item_id, quantity)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)
                """,
                (item_id, canteen),
            )

        # ------------------ CORRECT WEIGHTED AVERAGE UPDATE ------------------
            cursor.execute(
                "SELECT total_qty, total_amount FROM items_master WHERE item_id=%s",
                (item_id,)
            )
            row = cursor.fetchone()

            old_qty = float(row["total_qty"] or 0)
            old_amount = float(row["total_amount"] or 0)

            new_total_qty = old_qty + total
            new_total_amount = old_amount + purchase_amount

            if new_total_qty > 0:
                new_price = new_total_amount / new_total_qty
            else:
                new_price = 0

            cursor.execute(
                """
                UPDATE items_master
                SET total_qty=%s, total_amount=%s, price=%s
                WHERE item_id=%s
                """,
                (new_total_qty, new_total_amount, new_price, item_id)
            )

            conn.commit()
            flash("Order Saved & Stocks Updated!", "success")
            return redirect(url_for("order_received"))

        # ---------- GET SECTION ----------
        cursor.execute("SELECT * FROM items_master ORDER BY item_name ASC")
        items = cursor.fetchall()

        cursor.execute("SELECT vendor_name FROM vendor_master ORDER BY vendor_name ASC")
        vendors = [v["vendor_name"] for v in cursor.fetchall()]

        today = date.today()
        from_30_days = today - timedelta(days=30)

        from_date = request.args.get("from_date", from_30_days.isoformat())
        to_date = request.args.get("to_date", today.isoformat())

        cursor.execute(
            """
            SELECT o.*, i.item_name
            FROM orders o
            JOIN items_master i ON o.item_id = i.item_id
            WHERE o.order_date BETWEEN %s AND %s
            ORDER BY o.id DESC
            """,
            (from_date, to_date),
        )
        orders = cursor.fetchall()

    finally:
        cursor.close()
        conn.close()

    return render_template(
        "order_received.html",
        items=items,
        orders=orders,
        from_date=from_date,
        to_date=to_date,
        vendors=vendors
    )




# ================== MANAGER DASHBOARD ==================
@app.route("/manager_dashboard")
@login_required
@role_required(["manager"])
def manager_dashboard():
    conn = get_connection()
    if not conn:
        flash("Database error!", "danger")
        return redirect(url_for("login"))

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT im.item_id,
                   im.item_name,im.price,
                   im.unit,
                   IFNULL(ms.quantity,0) AS mess_qty,
                   IFNULL(cs.quantity,0) AS canteen_qty,
                   IFNULL(ms.quantity,0) + IFNULL(cs.quantity,0) AS total_qty
            FROM items_master im
            LEFT JOIN mess_stock ms ON im.item_id = ms.item_id
            LEFT JOIN canteen_stock cs ON im.item_id = cs.item_id
            ORDER BY im.item_name
            """
        )
        stock = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template("manager_dashboard.html", stock=stock)


# ================== MESS DASHBOARD ==================
@app.route("/mess_dashboard", methods=["GET", "POST"])
@login_required
@role_required(["mess", "manager"])
def mess_dashboard():
    conn = get_connection()
    if not conn:
        flash("Database error!", "danger")
        return redirect(url_for("login"))

    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "POST":
            item_name = request.form["item_name"]
            try:
                qty = float(request.form["quantity"])
            except Exception:
                flash("Invalid quantity.", "danger")
                return redirect(url_for("mess_dashboard"))

            # item id + stock in one go
            cursor.execute(
                """
                SELECT im.item_id,
                       IFNULL(ms.quantity,0) AS stock
                FROM items_master im
                LEFT JOIN mess_stock ms ON im.item_id = ms.item_id
                WHERE im.item_name=%s
                """,
                (item_name,),
            )
            row = cursor.fetchone()

            if not row:
                flash("Item not found!", "danger")
                return redirect(url_for("mess_dashboard"))

            if row["stock"] < qty:
                flash("Not enough stock!", "danger")
                return redirect(url_for("mess_dashboard"))

            # update stock
            cursor.execute(
                "UPDATE mess_stock SET quantity = quantity - %s WHERE item_id=%s",
                (qty, row["item_id"]),
            )

            # insert usage
            cursor.execute(
                """
                INSERT INTO mess_usage (item_id, quantity_used, used_date)
                VALUES (%s, %s, %s)
                """,
                (row["item_id"], qty, date.today()),
            )
            conn.commit()
            flash(f"Used {qty} units of {item_name}.", "success")
            return redirect(url_for("mess_dashboard"))

        # GET: stock
        cursor.execute(
            """
            SELECT im.item_name,
            ms.quantity,
            im.unit
            FROM mess_stock ms
            JOIN items_master im ON im.item_id = ms.item_id
            WHERE ms.quantity > 0
            ORDER BY im.item_name;
            """
        )
        stock = cursor.fetchall()

        # GET: usage by date
        selected_date = request.args.get("selected_date", date.today().isoformat())
        cursor.execute(
            """
            SELECT i.item_name,i.unit, u.quantity_used, u.used_date
            FROM mess_usage u
            JOIN items_master i ON u.item_id = i.item_id
            WHERE u.used_date=%s
            ORDER BY u.id DESC
            """,
            (selected_date,),
        )
        usage = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    filters = {"selected_date": selected_date}
    return render_template("mess_dashboard.html", stock=stock, usage=usage, filters=filters)


# ================== CANTEEN DASHBOARD ==================
@app.route("/canteen_dashboard", methods=["GET", "POST"])
@login_required
@role_required(["canteen", "manager"])
def canteen_dashboard():
    conn = get_connection()
    if not conn:
        flash("Database error!", "danger")
        return redirect(url_for("login"))

    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "POST":
            item_name = request.form["item_name"]
            try:
                qty = float(request.form["quantity"])
            except Exception:
                flash("Invalid quantity.", "danger")
                return redirect(url_for("canteen_dashboard"))

            cursor.execute(
                """
                SELECT im.item_id,
                       IFNULL(cs.quantity,0) AS stock
                FROM items_master im
                LEFT JOIN canteen_stock cs ON im.item_id = cs.item_id
                WHERE im.item_name=%s
                """,
                (item_name,),
            )
            row = cursor.fetchone()

            if not row:
                flash("Item not found!", "danger")
                return redirect(url_for("canteen_dashboard"))

            if row["stock"] < qty:
                flash("Insufficient stock!", "danger")
                return redirect(url_for("canteen_dashboard"))

            cursor.execute(
                "UPDATE canteen_stock SET quantity = quantity - %s WHERE item_id=%s",
                (qty, row["item_id"]),
            )

            cursor.execute(
                """
                INSERT INTO canteen_usage (item_id, quantity_used, used_date)
                VALUES (%s, %s, %s)
                """,
                (row["item_id"], qty, date.today()),
            )

            conn.commit()
            flash(f"Used {qty} units of {item_name}.", "success")
            return redirect(url_for("canteen_dashboard"))

        # GET: stock
        cursor.execute(
            """
            SELECT im.item_name,
            cs.quantity,
            im.unit
            FROM canteen_stock cs
            JOIN items_master im ON im.item_id = cs.item_id
            WHERE cs.quantity > 0
            ORDER BY im.item_name
            """
        )
        stock = cursor.fetchall()

        selected_date = request.args.get("selected_date", date.today().isoformat())
        cursor.execute(
            """
            SELECT i.item_name,i.unit, u.quantity_used, u.used_date
            FROM canteen_usage u
            JOIN items_master i ON u.item_id = i.item_id
            WHERE u.used_date=%s
            ORDER BY u.id DESC
            """,
            (selected_date,),
        )
        usage = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    filters = {"selected_date": selected_date}
    return render_template(
        "canteen_dashboard.html", stock=stock, usage=usage, filters=filters
    )


# ================== USAGE REPORT ==================
@app.route("/usage_report", methods=["GET", "POST"])
@login_required
def usage_report():
    conn = get_connection()
    if not conn:
        flash("Database error!", "danger")
        return redirect(url_for("login"))

    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "POST":
            usage_type = request.form.get("usage_type", "both")
            from_date = request.form.get("from_date", date.today().isoformat())
            to_date = request.form.get("to_date", date.today().isoformat())
            export_csv = request.form.get("export_csv")
        else:
            usage_type = request.args.get("usage_type", "both")
            from_date = request.args.get("from_date", date.today().isoformat())
            to_date = request.args.get("to_date", date.today().isoformat())
            export_csv = None

        query_parts = []
        params = []

        if usage_type in ["mess", "both"]:
            query_parts.append(
                """
                SELECT 'Mess' AS source, i.item_name,i.unit, u.quantity_used, u.used_date
                FROM mess_usage u
                JOIN items_master i ON u.item_id = i.item_id
                WHERE u.used_date BETWEEN %s AND %s
                """
            )
            params.extend([from_date, to_date])

        if usage_type in ["canteen", "both"]:
            query_parts.append(
                """
                SELECT 'Canteen' AS source, i.item_name,i.unit, u.quantity_used, u.used_date
                FROM canteen_usage u
                JOIN items_master i ON u.item_id = i.item_id
                WHERE u.used_date BETWEEN %s AND %s
                """
            )
            params.extend([from_date, to_date])

        if not query_parts:
            results = []
        else:
            if len(query_parts) == 2:
                final_query = (
                    f"{query_parts[0]} UNION ALL {query_parts[1]} ORDER BY used_date DESC"
                )
            else:
                final_query = query_parts[0] + " ORDER BY used_date DESC"

            cursor.execute(final_query, tuple(params))
            results = cursor.fetchall()

        # SUMMARY
        summary = []
        if usage_type in ["mess", "canteen"]:
            table = "mess_usage" if usage_type == "mess" else "canteen_usage"
            source_name = usage_type.capitalize()
            cursor.execute(
                f"""
                SELECT i.item_name,i.unit,
                       SUM(u.quantity_used) AS total_used,
                       %s AS source
                FROM {table} u
                JOIN items_master i ON u.item_id = i.item_id
                WHERE u.used_date BETWEEN %s AND %s
                GROUP BY i.item_name
                ORDER BY i.item_name
                """,
                (source_name, from_date, to_date),
            )
            summary = cursor.fetchall()
        elif usage_type == "both":
            cursor.execute(
                """
                SELECT i.item_name,i.unit,
                       SUM(u.quantity_used) AS total_used,
                       'Both' AS source
                FROM (
                    SELECT item_id, quantity_used
                    FROM mess_usage
                    WHERE used_date BETWEEN %s AND %s
                    UNION ALL
                    SELECT item_id, quantity_used
                    FROM canteen_usage
                    WHERE used_date BETWEEN %s AND %s
                ) u
                JOIN items_master i ON u.item_id = i.item_id
                GROUP BY i.item_name
                ORDER BY i.item_name
                """,
                (from_date, to_date, from_date, to_date),
            )
            summary = cursor.fetchall()

        # CSV EXPORT
        if export_csv:
            si = StringIO()
            cw = csv.writer(si)

            cw.writerow(["No.", "Source", "Item Name", "Quantity Used", "Date"])
            for idx, r in enumerate(results or [], start=1):
                cw.writerow(
                    [
                        idx,
                        r.get("source"),
                        r.get("item_name"),
                        float(r.get("quantity_used") or 0),
                        r.get("used_date"),
                    ]
                )

            cw.writerow([])

            cw.writerow(["Summary"])
            cw.writerow(["No.", "Item Name", "Total Quantity Used", "Source"])
            for idx, s in enumerate(summary or [], start=1):
                cw.writerow(
                    [
                        idx,
                        s.get("item_name"),
                        float(s.get("total_used") or 0),
                        s.get("source"),
                    ]
                )

            output = make_response(si.getvalue())
            output.headers[
                "Content-Disposition"
            ] = f"attachment; filename=usage_report_{from_date}_to_{to_date}.csv"
            output.headers["Content-type"] = "text/csv"
            return output

    finally:
        cursor.close()
        conn.close()

    return render_template(
        "usage_report.html",
        results=results or [],
        summary=summary or [],
        usage_type=usage_type,
        from_date=from_date,
        to_date=to_date,
    )


# ================== EXPORT STOCK CSV ==================
@app.route("/export_stock_csv")
@login_required
def export_stock_csv():
    conn = get_connection()
    if not conn:
        flash("Database error!", "danger")
        return redirect(url_for("manager_dashboard"))

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT im.item_id,
                   im.item_name,
                   im.unit,im.price,
                   IFNULL(ms.quantity,0) AS mess_qty,
                   IFNULL(cs.quantity,0) AS canteen_qty,
                   IFNULL(ms.quantity,0) + IFNULL(cs.quantity,0) AS total_qty
            FROM items_master im
            LEFT JOIN mess_stock ms ON im.item_id = ms.item_id
            LEFT JOIN canteen_stock cs ON im.item_id = cs.item_id
            ORDER BY im.item_name
            """
        )
        stock = cursor.fetchall()

        si = StringIO()
        cw = csv.writer(si)
        cw.writerow(
            ["Item ID", "Item Name", "Mess Stock", "Canteen Stock", "Total Stock", "Unit","value","Price/unit"]
        )

        for s in stock or []:
            total_amount = float(s.get("total_qty") or 0) * float(s.get("price") or 0)
            cw.writerow(
                [
                    s.get("item_id"),
                    s.get("item_name"),
                    float(s.get("mess_qty") or 0),
                    float(s.get("canteen_qty") or 0),
                    float(s.get("total_qty") or 0),
                    s.get("unit"),
                    total_amount,
                    float(s.get("price") or 0),
                ]
            )

        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = "attachment; filename=stock_report.csv"
        output.headers["Content-type"] = "text/csv"
        return output
    finally:
        cursor.close()
        conn.close()


# ================== CHANGE PASSWORD ==================
@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    username = session.get("username")
    if not username:
        flash("Please login first.", "danger")
        return redirect(url_for("login"))

    conn = get_connection()
    if not conn:
        flash("Database error!", "danger")
        return redirect(url_for("login"))

    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "POST":
            old_password = request.form["old_password"]
            new_password = request.form["new_password"]
            confirm_password = request.form["confirm_password"]

            cursor.execute(
                "SELECT password FROM users WHERE username=%s", (username,)
            )
            user = cursor.fetchone()
            if not user:
                flash("User not found!", "danger")
                return redirect(url_for("change_password"))

            if user["password"] != old_password:
                flash("Old password is incorrect!", "danger")
                return redirect(url_for("change_password"))

            if new_password != confirm_password:
                flash("New password and confirm password do not match!", "danger")
                return redirect(url_for("change_password"))

            cursor.execute(
                "UPDATE users SET password=%s WHERE username=%s",
                (new_password, username),
            )
            conn.commit()
            flash("Password updated successfully!", "success")
            return redirect(url_for("change_password"))
    finally:
        cursor.close()
        conn.close()

    return render_template("change_password.html")

@app.route("/export_orders_csv")
@login_required
def export_orders_csv():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    today = date.today()
    from_30_days = today - timedelta(days=30)

    from_date = request.args.get("from_date", from_30_days.isoformat())
    to_date = request.args.get("to_date", today.isoformat())

    cursor.execute(
        """
        SELECT o.*, i.item_name
        FROM orders o
        JOIN items_master i ON o.item_id = i.item_id
        WHERE o.order_date BETWEEN %s AND %s
        ORDER BY o.id DESC
        """,
        (from_date, to_date),
    )
    orders = cursor.fetchall()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["Vendor", "Item", "Qty", "Unit", "Amount", "Mess", "Canteen", "Date"])

    for o in orders:
        cw.writerow([
            o["vendor_name"],
            o["item_name"],
            o["total_qty"],
            o["unit"],
            o["price"],
            o["mess_qty"],
            o["canteen_qty"],
            o["order_date"].strftime("%d-%m-%Y")
        ])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=purchase_history.csv"
    output.headers["Content-Type"] = "text/csv"
    return output

@app.route("/transfer_stock", methods=["GET", "POST"])
@login_required
def transfer_stock():
    conn = get_connection()
    if not conn:
        flash("Database error!", "danger")
        return redirect(url_for("login"))

    cursor = conn.cursor(dictionary=True)

    role = session.get("role")

    # ---------- AUTO FROM/TO LOGIC ----------
    if role == "mess":
        transfer_from_default = "mess"
        transfer_to_default = "canteen"
        editable = False
    elif role == "canteen":
        transfer_from_default = "canteen"
        transfer_to_default = "mess"
        editable = False
    else:
        # Manager → editable
        transfer_from_default = "mess"
        transfer_to_default = "canteen"
        editable = True

    try:
        if request.method == "POST":

            # Manager only can change
            if editable:
                transfer_from = request.form.get("transfer_from")
                transfer_to = request.form.get("transfer_to")
            else:
                transfer_from = transfer_from_default
                transfer_to = transfer_to_default

            item_id = request.form["item_id"]
            qty = float(request.form["quantity"])

            # Fetch item + stocks
            cursor.execute(
                """
                SELECT im.item_id, im.item_name, im.unit,
                       IFNULL(ms.quantity,0) AS mess_qty,
                       IFNULL(cs.quantity,0) AS canteen_qty
                FROM items_master im
                LEFT JOIN mess_stock ms ON im.item_id = ms.item_id
                LEFT JOIN canteen_stock cs ON im.item_id = cs.item_id
                WHERE im.item_id=%s
                """,
                (item_id,)
            )
            item = cursor.fetchone()

            # STOCK VALIDATION
            if transfer_from == "mess":
                if item["mess_qty"] < qty:
                    flash("Mess does not have enough stock!", "danger")
                    return redirect(url_for("transfer_stock"))
            else:
                if item["canteen_qty"] < qty:
                    flash("Canteen does not have enough stock!", "danger")
                    return redirect(url_for("transfer_stock"))

            # DEDUCT
            if transfer_from == "mess":
                cursor.execute(
                    "UPDATE mess_stock SET quantity = quantity - %s WHERE item_id=%s",
                    (qty, item_id)
                )
            else:
                cursor.execute(
                    "UPDATE canteen_stock SET quantity = quantity - %s WHERE item_id=%s",
                    (qty, item_id)
                )

            # ADD
            if transfer_to == "mess":
                cursor.execute(
                    """
                    INSERT INTO mess_stock (item_id, quantity)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)
                    """,
                    (item_id, qty)
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO canteen_stock (item_id, quantity)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)
                    """,
                    (item_id, qty)
                )

            conn.commit()

            flash(
                f"Transferred {qty} {item['unit']} of {item['item_name']} ({transfer_from} → {transfer_to})",
                "success",
            )
            return redirect(url_for("transfer_stock"))

        # Load items for dropdown
        cursor.execute("SELECT item_id, item_name, unit FROM items_master ORDER BY item_name ASC")
        items = cursor.fetchall()

    finally:
        cursor.close()
        conn.close()

    return render_template(
        "transfer_stock.html",
        items=items,
        transfer_from_default=transfer_from_default,
        transfer_to_default=transfer_to_default,
        editable=editable
    )




# ================== LOGOUT ==================
@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ================== RUN APP ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5151, debug=False)
