// Draws a world map in every element with class "map" and colours the countries whose
// ISO numeric codes are listed in its data-lit attribute.
(function () {
  const WORLD = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json";
  const maps = document.querySelectorAll(".map");
  if (!maps.length || !window.d3 || !window.topojson) return;

  d3.json(WORLD).then(world => {
    const countries = topojson.feature(world, world.objects.countries).features
      .filter(f => f.id !== "010"); // drop Antarctica
    maps.forEach(el => {
      const lit = new Set(JSON.parse(el.dataset.lit || "[]"));
      const width = 960, height = 480;
      const projection = d3.geoNaturalEarth1().fitSize([width, height],
        { type: "FeatureCollection", features: countries });
      const path = d3.geoPath(projection);
      const svg = d3.select(el).append("svg")
        .attr("viewBox", `0 0 ${width} ${height}`)
        .attr("role", "img")
        .attr("aria-label", `World map, ${lit.size} countries highlighted`);
      svg.selectAll("path").data(countries).join("path")
        .attr("d", path)
        .attr("class", d => lit.has(d.id) ? "lit" : null)
        .append("title").text(d => d.properties.name);
    });
  }).catch(() => { maps.forEach(el => el.textContent = "Map unavailable offline."); });
})();
