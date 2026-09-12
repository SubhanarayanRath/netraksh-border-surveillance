import sqlite3

conn = sqlite3.connect('netraksh.db')
curs = conn.cursor()

curs.execute('''
    SELECT 
        id, camera_id, timestamp, score_d, score_t, score_s, score_h, score_r, 
        corroboration_score, corroborated_by_event_id, corroboration_distance_m, 
        corroboration_delta_t_s, corroboration_t_expected_s, corroboration_sigma_s
    FROM events 
    WHERE corroboration_score IS NOT NULL 
    ORDER BY timestamp DESC 
    LIMIT 1
''')
row = curs.fetchone()
if row:
    keys = ['id', 'camera_id', 'timestamp', 'score_d', 'score_t', 'score_s', 'score_h', 'score_r', 
            'corroboration_score', 'corroborated_by_event_id', 'corroboration_distance_m', 
            'corroboration_delta_t_s', 'corroboration_t_expected_s', 'corroboration_sigma_s']
    data = dict(zip(keys, row))
    for k, v in data.items():
        print(f"{k}: {v}")
    
    print("\n--- Secondary Event ---")
    curs.execute('''
        SELECT id, camera_id, timestamp, score_d, score_t, score_s, score_h, score_r
        FROM events WHERE id = ?
    ''', (data['corroborated_by_event_id'],))
    row2 = curs.fetchone()
    keys2 = ['id', 'camera_id', 'timestamp', 'score_d', 'score_t', 'score_s', 'score_h', 'score_r']
    data2 = dict(zip(keys2, row2))
    for k, v in data2.items():
        print(f"{k}: {v}")

else:
    print("No corroborated events found.")
