import sqlite3

def check_db():
    conn = sqlite3.connect('d:/SIH/netraksh/netraksh.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, latitude, longitude FROM cameras")
    rows = cursor.fetchall()
    for row in rows:
        print(f"Camera: {row[0]}, Name: {row[1]}, Lat: {row[2]}, Lon: {row[3]}")
    conn.close()

if __name__ == "__main__":
    check_db()
