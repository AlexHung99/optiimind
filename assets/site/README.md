# Homepage assets

The homepage previously stored all fonts, images and the rendering runtime in a base64 bundle. It now serves normal cacheable files.

- `index.html` stores the existing three-style template as JSON in `#site-template`, with the original page logic in `[data-dc-script]`.
- `runtime.js` is extracted from the original bundle. Its site-specific changes read that JSON directly, avoid fetching the current page a second time, and use the pinned local React files in `../vendor/`. Do not overwrite it with the unmodified generated runtime.
- `fonts.css` retains the original fonts and Unicode subsets. Faces using the same font file and descriptors share a weight range. Fonts are requested by the browser only when matching visible text; `font-display: swap` remains enabled.
- `fonts/` and `images/` contain the original embedded assets, named by content hash.
- Product WebP files are quality-85 copies of the retained PNG sources. Below-the-fold screenshots use lazy loading; hero images remain eager. Social preview metadata retains PNG compatibility.

Validation: local Edge checks cover EN/ZH switching, product navigation, all three homepage styles, no repeated idle DOM mutations, no homepage self-fetch or unpkg requests, and decoding product images. Google Analytics is stubbed during these checks. These checks do not measure production network speed.
