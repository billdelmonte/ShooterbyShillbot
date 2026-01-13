import sqlite3

conn = sqlite3.connect("shillbot.sqlite3")
cur = conn.cursor()
cur.execute("DELETE FROM payout_transactions WHERE window_id = 'CURRENT'")
conn.commit()
print("✅ payout_transactions for CURRENT cleared")
conn.close()
