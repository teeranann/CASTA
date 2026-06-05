# CASTA — Contact Angle & Surface Tension Analyzer

A desktop app (Python · Tkinter · OpenCV) for **drop-shape analysis** from images
and videos:

- **Sessile drop → contact angle**
- **Pendant drop → surface tension**

Load an image or video, calibrate the scale, set the ROI and baseline, and read
the contact angle and surface tension off the fitted drop profile.

## Run

```
pip install opencv-python numpy pillow
python casta.py
```

## License

This is **noncommercial open software** (not OSI "open source" — commercial use is reserved):

- **Software** (the CASTA analyzer): **PolyForm Noncommercial 1.0.0** — see [`LICENSE`](LICENSE)
- **Documentation, images, sample data:** **CC BY‑NC 4.0**

You may **use, study, modify, and share** for **noncommercial** purposes
(education, research, schools, universities) **with attribution**. **Selling the
software or code, or any commercial use, is prohibited** without written
permission. See [`NOTICE`](NOTICE). For commercial licensing, contact
Teeranan Nongnual <teeranan.no@buu.ac.th>.

## Citation

If you use CASTA in academic work, please cite it — see [`CITATION.cff`](CITATION.cff).

## Author

**Teeranan Nongnual**<br>
Department of Chemistry, Faculty of Science, Burapha University, Thailand

## Funding

Burapha University (BUU) and Thailand Science Research and Innovation (TSRI).

## Acknowledgements

This software was developed with support from a research grant by Burapha
University and Thailand Science Research and Innovation (TSRI).

Copyright © 2026 Teeranan Nongnual.
