def setting(db):
    try:
        d = {}
        rows = db.query("SELECT * FROM setting")
        for r in rows:
            d[r[0]] = r[1]
        return d
    except:
        return {}
