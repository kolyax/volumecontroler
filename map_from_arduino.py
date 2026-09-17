def map_value(v, r1s, r1e, r2s, r2e):
    return r2s + (v - r1s) * (r2e - r2s) / (r1e - r1s)
