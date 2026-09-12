import sqlite3
import sys
import os

# Add the project root to sys.path so we can import backend modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from backend.security.auth import hash_password

def reset_passwords():
    # Connect to the SQLite DB
    conn = sqlite3.connect('d:/SIH/netraksh/netraksh.db')
    cursor = conn.cursor()
    
    # The default users
    users = ['admin', 'operator', 'auditor']
    
    for username in users:
        # Generate the new bcrypt hash using the backend's own function
        # The password is set to be identical to the username
        hashed_pw = hash_password(username)
        
        # Update the database
        cursor.execute("UPDATE users SET hashed_password = ? WHERE username = ?", (hashed_pw, username))
        print(f"Password reset for '{username}'")
        
    conn.commit()
    conn.close()
    print("All passwords successfully reset.")

if __name__ == "__main__":
    try:
        reset_passwords()
    except Exception as e:
        print(f"Error: {e}")
