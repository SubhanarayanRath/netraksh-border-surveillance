import sqlite3

def fix_coords():
    # Connect to the local SQLite DB
    conn = sqlite3.connect('d:/SIH/netraksh/netraksh.db')
    cursor = conn.cursor()
    
    # Update cam-border-01 to 74.6050
    cursor.execute("UPDATE cameras SET longitude = 74.6050 WHERE id = 'cam-border-01'")
    
    # Update cam-checkpoint-01 to 74.6025
    cursor.execute("UPDATE cameras SET longitude = 74.6025 WHERE id = 'cam-checkpoint-01'")
    
    conn.commit()
    conn.close()
    print("Database coordinates successfully shifted East into Indian territory.")

if __name__ == "__main__":
    try:
        fix_coords()
    except Exception as e:
        print(f"Error: {e}")
