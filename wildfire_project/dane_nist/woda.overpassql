/* Rzeki i jezioro Oroville w rejonie Camp Fire (OpenStreetMap, Overpass API).
   Prostokąt: (południe, zachód, północ, wschód). */
[out:json][timeout:120];
(
  way["waterway"="river"](39.50,-121.85,39.90,-121.35);
  way["waterway"]["name"="Butte Creek"](39.50,-121.85,39.90,-121.35);
  relation["natural"="water"]["name"="Lake Oroville"];
  way["natural"="water"]["name"="Lake Oroville"];
);
out geom;
