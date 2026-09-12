import sqlite3
import json
import os

def dump():
    conn = sqlite3.connect('d:/SIH/netraksh/netraksh.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, latitude, longitude FROM cameras")
    rows = cursor.fetchall()
    
    out = []
    for r in rows:
        out.append({'id': r[0], 'lat': r[1], 'lon': r[2]})
    
    # Save to scratch directory in artifact dir
    # wait, just print it, and I'll redirect the output in run_command? No, run_command might fail.
    # I'll save it locally to a file in d:\SIH\netraksh\db_dump.json
    with open('d:/SIH/netraksh/db_dump.json', 'w') as f:
        json.dump(out, f)
        
    conn.close()

if __name__ == "__main__":
    dump()
