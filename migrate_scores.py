import sqlite3

def migrate():
    conn = sqlite3.connect('netraksh.db')
    curs = conn.cursor()
    columns_to_add = ['score_d', 'score_t', 'score_s', 'score_h', 'score_r']
    
    # Check existing columns
    curs.execute("PRAGMA table_info(events)")
    existing_columns = [row[1] for row in curs.fetchall()]
    
    for col in columns_to_add:
        if col not in existing_columns:
            print(f"Adding column {col} to events...")
            curs.execute(f"ALTER TABLE events ADD COLUMN {col} FLOAT")
            
    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == '__main__':
    migrate()
