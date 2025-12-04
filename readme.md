📦 Stokit – Inventory Management System
A secure and efficient inventory management system designed for Mess, Canteen & Manager-level operations.
Built using Flask (Python) + MySQL (AWS RDS) + Nginx + Gunicorn.

📌 Features
✅ Role-based Login
Manager

Mess

Canteen

✅ Purchase Management
Vendor-wise purchase entry

Automatic weighted average price update

Stock auto-update (Mess + Canteen)

✅ Stock Dashboard
Real-time stock view

Mess & Canteen stock separation

Export to CSV

✅ Usage Records
Daily usage tracking

Summary report

CSV export

✅ Secure Hosting (AWS)
EC2 Ubuntu server

RDS MySQL

Nginx reverse proxy

Daily automated backups

🔐 Security Measures
1. Authentication Security
Role-based login

Strong password recommendation

Session expiration after inactivity

Optional brute-force protection

Lock account after 5 wrong attempts

5-minute cooldown

2. Server Security
Ubuntu server with UFW Firewall

Only necessary ports open

22 (SSH) – restricted by IP  
80/443 – HTTPS  
3306 – Only allowed for EC2 → RDS
All unused ports blocked

Systemd monitoring for Flask (auto restart)

3. Data Security
SSL-enabled communication between EC2 ↔ RDS

IAM-based DB security

RDS security group whitelisted to EC2 only

Passwords stored securely (hashed recommended)

📁 Backup System (AWS)
1. Automated Backups
AWS RDS provides:

Daily automated backups

Retention: 7–30 days

Point-in-time recovery

No manual work required

2. Manual Backup (Optional)
mysqldump -h database-endpoint -u admin -p rbmi_inventory > backup.sql
3. Restore Backup
mysql -h database-endpoint -u admin -p rbmi_inventory < backup.sql
🛠 Update Procedure (Production Deployment)
Step 1: Connect to Server
ssh -i "mess_canteen.pem" ubuntu@65.0.7.205
Step 2: Move to Project Directory
cd rbmi-inventory
Step 3: Pull Latest Code
git pull
Step 4: Activate Virtual Environment
source venv/bin/activate
Step 5: Install New Dependencies
pip install -r requirements.txt
Step 6: Restart Flask Service
sudo systemctl restart flaskapp
Step 7: View Logs (Optional)
sudo journalctl -u flaskapp -f
📎 Notes for Client
System automatically creates daily RDS backups.

Stock calculations are fully automated.

Only authorised technical person should update code.

System auto-restores itself on crash (Systemd restart policy).
