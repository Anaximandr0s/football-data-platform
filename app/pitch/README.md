# Pitch component

`pitch.js`: the canvas drawing of the MatchLens pitch, loaded by `app/streamlit/pitch.py` as a Streamlit custom component
v2 (docs/product.md, section 8.2). Our own code, no library and no build step: a library added later (d3-delaunay for the
Voronoi cells of the Replay) is kept here as a file, so the demo works offline:
`d3-delaunay.min.js` (6.0.4, ISC, licence in `d3-delaunay.LICENSE`, listed in the repository's `NOTICE`).
