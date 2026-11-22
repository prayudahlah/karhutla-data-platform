/* Dashboard Gold: baca API serving, render SVG tanpa library eksternal. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = { start: "2026-09-01", end: "2026-09-30", province: "" };

  const number = new Intl.NumberFormat("id-ID");
  const decimal = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 1 });

  const compact = (value) => {
    const n = Number(value) || 0;
    if (Math.abs(n) >= 1_000_000) return decimal.format(n / 1_000_000) + " jt";
    if (Math.abs(n) >= 1_000) return decimal.format(n / 1_000) + " rb";
    return number.format(n);
  };

  const isoDate = (date) => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
  };

  const dateLong = (iso) => {
    if (!iso) return "—";
    return new Date(iso + "T00:00:00").toLocaleDateString("id-ID", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  };

  const dateShort = (iso) => {
    if (!iso) return "";
    return new Date(iso + "T00:00:00").toLocaleDateString("id-ID", {
      day: "numeric",
      month: "short",
    });
  };

  const monthLong = (month) => {
    if (!month) return "—";
    return new Date(month + "-01T00:00:00").toLocaleDateString("id-ID", {
      month: "long",
      year: "numeric",
    });
  };

  const scarPeriodLabel = (rows) => {
    const months = [
      ...new Set((rows || []).map((row) => row.burn_month).filter(Boolean)),
    ].sort();
    if (!months.length) return monthLong(state.start.slice(0, 7));
    if (months.length === 1) return monthLong(months[0]);
    return monthLong(months[0]) + " – " + monthLong(months[months.length - 1]);
  };

  const periodLabel = () => {
    const start = new Date(state.start + "T00:00:00");
    const end = new Date(state.end + "T00:00:00");
    if (
      start.getFullYear() === end.getFullYear() &&
      start.getMonth() === end.getMonth()
    ) {
      return start.toLocaleDateString("id-ID", {
        month: "long",
        year: "numeric",
      });
    }
    return (
      start.toLocaleDateString("id-ID", { day: "numeric", month: "short" }) +
      " – " +
      end.toLocaleDateString("id-ID", {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    );
  };

  const sum = (rows, key) =>
    (rows || []).reduce((total, row) => total + Number(row[key] || 0), 0);

  const max = (rows, key) =>
    (rows || []).reduce(
      (value, row) => Math.max(value, Number(row[key] || 0)),
      0,
    );

  const niceMax = (value) => {
    if (!Number.isFinite(value) || value <= 0) return 1;
    const exponent = Math.floor(Math.log10(value));
    const base = Math.pow(10, exponent);
    const fraction = value / base;
    const steps = [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10];
    const step = steps.find((candidate) => fraction <= candidate) || 10;
    return step * base;
  };

  const getJson = async (url) => {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(url + " → HTTP " + response.status);
    return response.json();
  };

  const showError = (message) => {
    const box = $("dash-error");
    box.textContent = message;
    box.hidden = false;
  };

  const hideError = () => {
    $("dash-error").hidden = true;
  };

  const setLoading = (loading) => {
    const button = $("dash-apply");
    if (button) button.disabled = loading;
    if (loading) $("freshness").textContent = "Memuat data…";
  };

  const query = (extra = {}) => {
    const params = new URLSearchParams({
      start: state.start,
      end: state.end,
      ...extra,
    });
    if (state.province) params.set("province", state.province);
    return params.toString();
  };

  const scarQuery = () => {
    const params = new URLSearchParams({ limit: "1000" });
    if (state.province) params.set("province", state.province);
    return params.toString();
  };

  const THEME_KEY = "jagahutan-theme";

  const PALETTES = {
    dark: {
      tier: {
        kuat: "#ff5a2b",
        sedang: "#ff8a3d",
        lemah: "#ffb02e",
        kandidat: "#4f9c75",
      },
      frp: "#ffb02e",
      treemap: [
        "#E8681F",
        "#2F7D57",
        "#3A8F66",
        "#4F9C75",
        "#67AD88",
        "#82BF9D",
        "#A0D0B4",
        "#BFE0C9",
      ],
      treemapOthers: "#5C6B62",
      mapLand: "#153a2b",
      mapStroke: "#3d7657",
      mapGrid: "#1b3a2d",
      mapLabel: "#8fb5a0",
      heat: [
        ["#173026", "#eaf3ec"],
        ["#2f5e49", "#f4fbf6"],
        ["#6f9c83", "#10241c"],
        ["#ffb02e", "#1a0d03"],
        ["#ff8a3d", "#1a0d03"],
        ["#ff5a2b", "#1a0d03"],
      ],
    },
    light: {
      tier: {
        kuat: "#e2402a",
        sedang: "#f2711c",
        lemah: "#e9a21b",
        kandidat: "#2f7d57",
      },
      frp: "#d9581e",
      treemap: [
        "#D9581E",
        "#1B4F36",
        "#266044",
        "#317054",
        "#3D8062",
        "#4F9070",
        "#65A184",
        "#7FB29A",
      ],
      treemapOthers: "#B7AF9F",
      mapLand: "#d8e2c5",
      mapStroke: "#9fb28e",
      mapGrid: "#e6e2d3",
      mapLabel: "#6d7f72",
      heat: [
        ["#f1ede2", "#8a978c"],
        ["#e6efe5", "#3f5c4c"],
        ["#c7ddc6", "#24402f"],
        ["#9dc79b", "#16241c"],
        ["#ffb02e", "#1a0d03"],
        ["#ff5a2b", "#1a0d03"],
      ],
    },
  };

  const isLight = () => document.documentElement.dataset.theme === "light";
  const palette = () => (isLight() ? PALETTES.light : PALETTES.dark);

  const escapeText = (value) =>
    String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  function hideTooltip() {
    const tooltip = $("chart-tooltip");
    if (!tooltip) return;
    tooltip.classList.remove("is-visible");
    tooltip.setAttribute("aria-hidden", "true");
  }

  function bindTooltips() {
    const workspace = document.querySelector(".dash-workspace");
    const tooltip = $("chart-tooltip");
    if (!workspace || !tooltip) return;
    const selector = "[data-tt-title], [data-tt-value]";
    let visible = false;

    const content = (target) => {
      const parts = [];
      if (target.dataset.ttKicker) {
        parts.push(
          '<div class="tt-kicker">' +
            escapeText(target.dataset.ttKicker) +
            "</div>",
        );
      }
      if (target.dataset.ttTitle) {
        parts.push(
          '<div class="tt-title">' +
            escapeText(target.dataset.ttTitle) +
            "</div>",
        );
      }
      if (target.dataset.ttValue) {
        parts.push(
          '<div class="tt-value">' +
            escapeText(target.dataset.ttValue) +
            "</div>",
        );
      }
      if (target.dataset.ttSub) {
        parts.push(
          '<div class="tt-sub">' + escapeText(target.dataset.ttSub) + "</div>",
        );
      }
      return parts.join("");
    };

    const place = (x, y) => {
      const rect = tooltip.getBoundingClientRect();
      const pad = 12;
      let left = x + 14;
      let top = y - rect.height - 14;
      if (left + rect.width + pad > window.innerWidth) {
        left = x - rect.width - 14;
      }
      if (top < pad) top = y + 18;
      tooltip.style.left = Math.max(pad, left) + "px";
      tooltip.style.top = Math.max(pad, top) + "px";
    };

    const show = (target, x, y) => {
      const html = content(target);
      if (!html) return;
      tooltip.innerHTML = html;
      tooltip.classList.add("is-visible");
      tooltip.setAttribute("aria-hidden", "false");
      visible = true;
      place(x, y);
    };

    workspace.addEventListener("pointerover", (event) => {
      const target = event.target.closest(selector);
      if (!target || target.contains(event.relatedTarget)) return;
      show(target, event.clientX, event.clientY);
    });
    workspace.addEventListener("pointermove", (event) => {
      if (!visible) return;
      const target = event.target.closest(selector);
      if (!target) return;
      place(event.clientX, event.clientY);
    });
    workspace.addEventListener("pointerout", (event) => {
      const target = event.target.closest(selector);
      if (!target) return;
      if (event.relatedTarget && target.contains(event.relatedTarget)) return;
      hideTooltip();
      visible = false;
    });
    workspace.addEventListener("focusin", (event) => {
      const target = event.target.closest(selector);
      if (!target) return;
      const rect = target.getBoundingClientRect();
      show(target, rect.left + rect.width / 2, rect.top);
    });
    workspace.addEventListener("focusout", (event) => {
      if (event.target.closest(selector)) {
        hideTooltip();
        visible = false;
      }
    });
    window.addEventListener(
      "wheel",
      () => {
        hideTooltip();
        visible = false;
      },
      { passive: true },
    );
    window.addEventListener(
      "touchmove",
      () => {
        hideTooltip();
        visible = false;
      },
      { passive: true },
    );
  }

  let lastData = null;

  function syncThemeButton() {
    const button = $("theme-toggle");
    if (!button) return;
    const light = isLight();
    button.setAttribute("aria-pressed", String(light));
    const label = button.querySelector(".theme-label");
    if (label) label.textContent = light ? "Gelap" : "Terang";
    const title = light ? "Ganti ke tema gelap" : "Ganti ke tema terang";
    button.setAttribute("aria-label", "Ganti tema");
    button.setAttribute("title", title);
  }

  function renderAll(data) {
    hideTooltip();
    const { summaryRows, dailyRows, monthlyRows, health, cells } = data;
    renderSummary(summaryRows, monthlyRows);
    renderSparkline(dailyRows, "spark-total");
    renderSparkline(dailyRows, "spark-peak");
    renderTierBar(summaryRows);
    renderInsight(summaryRows, dailyRows);
    renderTrendKpis(dailyRows);
    renderTierChart(dailyRows);
    renderDailyStrip(dailyRows);
    renderMap(cells, summaryRows);
    renderTreemap(summaryRows);
    renderLineChart(
      "chart-frp",
      dailyRows,
      "frp_sum",
      "frp-peak",
      palette().frp,
    );
    renderTop(
      "top-hotspot",
      summaryRows,
      "hotspot_count",
      false,
      sum(summaryRows, "hotspot_count"),
    );
    renderDonut(summaryRows);

    const hotspotTotal = sum(summaryRows, "hotspot_count");
    const kandidat = sum(summaryRows, "hotspot_kandidat");
    $("top-hotspot-note").textContent = summaryRows.length
      ? summaryRows.length +
        " provinsi · " +
        number.format(hotspotTotal) +
        " hotspot"
      : "Belum ada data pada rentang ini.";
    $("donut-note").textContent = hotspotTotal
      ? "Kandidat " +
        decimal.format((kandidat / hotspotTotal) * 100) +
        "% dari total"
      : "Belum ada data pada rentang ini.";
    renderFreshness(health);
  }

  function applyTheme(theme, persist) {
    if (theme === "light") {
      document.documentElement.dataset.theme = "light";
    } else {
      delete document.documentElement.dataset.theme;
    }
    if (persist) {
      try {
        localStorage.setItem(THEME_KEY, theme);
      } catch (error) {}
    }
    syncThemeButton();
    if (lastData) renderAll(lastData);
  }

  function bindTheme() {
    const button = $("theme-toggle");
    if (!button) return;
    button.addEventListener("click", () => {
      applyTheme(isLight() ? "dark" : "light", true);
    });
    syncThemeButton();
  }

  function renderSummary(summaryRows, monthlyRows) {
    const total = sum(summaryRows, "hotspot_count");
    const kuat = sum(summaryRows, "hotspot_kuat");
    const frp = sum(summaryRows, "frp_sum");
    const frpMax = max(summaryRows, "frp_max");
    const scar = sum(monthlyRows, "scar_area_km2");
    const scarPixels = sum(monthlyRows, "scar_pixels");
    const provinceCount = (summaryRows || []).length;

    $("tab1-total").textContent = number.format(total);
    $("tab1-total-sub").textContent = periodLabel();

    $("tab1-kuat").textContent = number.format(kuat);
    $("tab1-kuat-sub").textContent = total
      ? decimal.format((kuat / total) * 100) + "% dari total hotspot"
      : "Tidak ada hotspot pada rentang ini";

    $("tab1-frp").textContent = decimal.format(frp / 1_000_000) + " jt";
    $("tab1-frp-sub").textContent =
      "\u03a3 MW \u00b7 maks provinsi " + number.format(frpMax) + " MW";

    $("tab1-scar").textContent = number.format(Math.round(scar));
    $("tab1-scar-sub").textContent =
      "km\u00b2 \u00b7 " +
      number.format(scarPixels) +
      " piksel \u00b7 " +
      scarPeriodLabel(monthlyRows);

    const activeCells = sum(summaryRows, "active_cell_days");
    $("tab1-active").textContent = number.format(activeCells);
    $("tab1-active-sub").textContent = "sel-hari \u00b7 grid 0,25\u00b0";

    $("rail-period").textContent = periodLabel();
    $("rail-coverage").textContent = provinceCount + " provinsi";
  }

  function renderSparkline(rows, id) {
    const svg = $(id);
    if (!svg) return;
    const values = [...(rows || [])]
      .sort((a, b) => String(a.date).localeCompare(String(b.date)))
      .map((row) => Number(row.hotspot_count || 0));
    if (values.length < 2) {
      svg.innerHTML = "";
      return;
    }
    const width = 120;
    const height = 30;
    const pad = 3;
    const maxValue = Math.max(...values, 1);
    const step = (width - pad * 2) / (values.length - 1);
    const points = values.map((value, index) => {
      const x = pad + index * step;
      const y = height - pad - (value / maxValue) * (height - pad * 2);
      return [x, y];
    });
    const line = points
      .map(
        ([x, y], index) =>
          (index ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1),
      )
      .join(" ");
    const lastX = points[points.length - 1][0].toFixed(1);
    const area =
      line +
      " L" +
      lastX +
      " " +
      (height - pad) +
      " L" +
      pad +
      " " +
      (height - pad) +
      " Z";
    svg.innerHTML =
      '<path d="' +
      area +
      '" fill="var(--amber)" opacity=".14"></path>' +
      '<path d="' +
      line +
      '" fill="none" stroke="var(--amber)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"></path>';
  }

  function renderTierBar(rows) {
    const host = $("kpi-tier");
    if (!host) return;
    const colors = palette().tier;
    const segments = [
      { value: sum(rows, "hotspot_kuat"), color: colors.kuat },
      { value: sum(rows, "hotspot_sedang"), color: colors.sedang },
      { value: sum(rows, "hotspot_lemah"), color: colors.lemah },
      { value: sum(rows, "hotspot_kandidat"), color: colors.kandidat },
    ].filter((segment) => segment.value > 0);
    const total = segments.reduce((value, segment) => value + segment.value, 0);
    if (!total) {
      host.innerHTML = "";
      return;
    }
    host.innerHTML = segments
      .map(
        (segment) =>
          '<i style="width:' +
          ((segment.value / total) * 100).toFixed(2) +
          "%;background:" +
          segment.color +
          '"></i>',
      )
      .join("");
  }

  function renderInsight(summaryRows, dailyRows) {
    const host = $("insight-text");
    if (!host) return;
    const total = sum(summaryRows, "hotspot_count");
    const top = [...(summaryRows || [])]
      .filter((row) => Number(row.hotspot_count || 0) > 0)
      .sort((a, b) => Number(b.hotspot_count) - Number(a.hotspot_count))[0];
    const kandidat = sum(summaryRows, "hotspot_kandidat");
    const peak = [...(dailyRows || [])]
      .filter((row) => row.date)
      .sort(
        (a, b) => Number(b.hotspot_count || 0) - Number(a.hotspot_count || 0),
      )[0];
    const parts = [];
    if (top && total) {
      parts.push(
        "<b>" +
          escapeText(top.province) +
          "</b> " +
          decimal.format((Number(top.hotspot_count) / total) * 100) +
          "% hotspot",
      );
    }
    if (total) {
      parts.push(
        "<b>" +
          decimal.format((kandidat / total) * 100) +
          "%</b> kandidat",
      );
    }
    if (peak) {
      parts.push(
        "Puncak <b>" +
          number.format(Math.round(Number(peak.hotspot_count || 0))) +
          "</b> pada " +
          dateShort(peak.date),
      );
    }
    host.innerHTML = parts.length
      ? parts.join('<span class="insight-sep" aria-hidden="true">·</span>')
      : "Belum ada insight pada rentang ini.";
  }

  function renderTrendKpis(dailyRows) {
    const rows = dailyRows || [];
    const days = rows.length;
    const total = sum(rows, "hotspot_count");
    const peak = [...rows].sort(
      (a, b) => Number(b.hotspot_count) - Number(a.hotspot_count),
    )[0];
    const frpPeak = [...rows].sort(
      (a, b) => Number(b.frp_sum) - Number(a.frp_sum),
    )[0];

    $("tab2-peak").textContent = peak
      ? number.format(Math.round(Number(peak.hotspot_count)))
      : "\u2014";
    $("tab2-peak-sub").textContent = peak
      ? "pada " + dateLong(peak.date)
      : "Belum ada data harian";

    $("tab2-avg").textContent = days
      ? number.format(Math.round(total / days))
      : "\u2014";
    $("tab2-avg-sub").textContent = "hotspot per hari";

    $("tab2-days").textContent = number.format(days);
    $("tab2-days-sub").textContent = "hari dengan data";

    $("tab2-frp").textContent = frpPeak
      ? compact(frpPeak.frp_sum)
      : "\u2014";
    $("tab2-frp-sub").textContent = frpPeak
      ? "Σ MW · " + dateShort(frpPeak.date)
      : "Belum ada data FRP";
  }

  function renderLineChart(svgId, rows, key, badgeId, color) {
    const svg = $(svgId);
    const badge = $(badgeId);
    const byDate = new Map(
      (rows || [])
        .filter((row) => row.date)
        .map((row) => [row.date, Number(row[key] || 0)]),
    );

    const domain = [];
    const cursor = new Date(state.start + "T00:00:00");
    const last = new Date(state.end + "T00:00:00");
    while (cursor <= last) {
      domain.push(isoDate(cursor));
      cursor.setDate(cursor.getDate() + 1);
    }
    const series = domain.map((date) =>
      byDate.has(date) ? byDate.get(date) : null,
    );
    const present = series
      .map((value, index) => ({ value, index }))
      .filter((point) => point.value !== null);

    if (!present.length) {
      svg.innerHTML =
        '<text x="240" y="130" text-anchor="middle" fill="var(--label)" font-size="14">Belum ada data.</text>';
      badge.textContent = "Tidak ada data";
      return;
    }

    const width = 480;
    const height = 260;
    const padL = 52;
    const padR = 14;
    const padT = 24;
    const padB = 38;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;
    const peak = present.reduce(
      (best, point) => (point.value > best.value ? point : best),
      present[0],
    );
    const yMax = niceMax(peak.value * 1.08);

    const xFor = (index) =>
      padL + (index * plotW) / Math.max(domain.length - 1, 1);
    const yFor = (value) => padT + plotH - (value / yMax) * plotH;

    const segments = [];
    let segment = [];
    series.forEach((value, index) => {
      if (value === null) {
        if (segment.length) segments.push(segment);
        segment = [];
      } else {
        segment.push({ index, value });
      }
    });
    if (segment.length) segments.push(segment);

    const linePaths = segments
      .map((points) => {
        const path = points
          .map(
            (point, index) =>
              (index ? "L" : "M") +
              xFor(point.index).toFixed(1) +
              " " +
              yFor(point.value).toFixed(1),
          )
          .join(" ");
        return (
          '<path d="' +
          path +
          '" fill="none" stroke="' +
          color +
          '" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />'
        );
      })
      .join("");

    const areaPaths = segments
      .filter((points) => points.length > 1)
      .map((points) => {
        const first = points[0];
        const lastPoint = points[points.length - 1];
        const path =
          "M " +
          xFor(first.index).toFixed(1) +
          " " +
          yFor(first.value).toFixed(1) +
          " " +
          points
            .slice(1)
            .map(
              (point) =>
                "L " +
                xFor(point.index).toFixed(1) +
                " " +
                yFor(point.value).toFixed(1),
            )
            .join(" ") +
          " L " +
          xFor(lastPoint.index).toFixed(1) +
          " " +
          (padT + plotH) +
          " L " +
          xFor(first.index).toFixed(1) +
          " " +
          (padT + plotH) +
          " Z";
        return '<path d="' + path + '" fill="url(#' + svgId + '-fill)" />';
      })
      .join("");

    const grid = [0, 1 / 3, 2 / 3, 1]
      .map((fraction) => {
        const y = padT + plotH - fraction * plotH;
        return (
          '<line x1="' +
          padL +
          '" y1="' +
          y.toFixed(1) +
          '" x2="' +
          (width - padR) +
          '" y2="' +
          y.toFixed(1) +
          '" stroke="var(--line)" stroke-width="1" />' +
          '<text x="' +
          (padL - 10) +
          '" y="' +
          (y + 4).toFixed(1) +
          '" text-anchor="end" fill="var(--label)" font-size="10">' +
          compact(yMax * fraction) +
          "</text>"
        );
      })
      .join("");

    const xIndexes = [0, Math.floor((domain.length - 1) / 2), domain.length - 1];
    const xLabels = xIndexes
      .map((index) => {
        const anchor =
          index === 0 ? "start" : index === domain.length - 1 ? "end" : "middle";
        return (
          '<text x="' +
          xFor(index).toFixed(1) +
          '" y="' +
          (height - 10) +
          '" text-anchor="' +
          anchor +
          '" fill="var(--label)" font-size="10">' +
          dateShort(domain[index]) +
          "</text>"
        );
      })
      .join("");

    const peakX = xFor(peak.index);
    const peakY = yFor(peak.value);
    const peakAnchor =
      peakX < padL + 48 ? "start" : peakX > width - padR - 48 ? "end" : "middle";
    const dots = present
      .map(
        (point) =>
          '<circle cx="' +
          xFor(point.index).toFixed(1) +
          '" cy="' +
          yFor(point.value).toFixed(1) +
          '" r="1.6" fill="' +
          color +
          '" opacity=".7" />',
      )
      .join("");

    const hits = present
      .map(
        (point) =>
          '<circle cx="' +
          xFor(point.index).toFixed(1) +
          '" cy="' +
          yFor(point.value).toFixed(1) +
          '" r="7" fill="transparent" pointer-events="all" data-tt-kicker="FRP harian" data-tt-title="' +
          escapeText(dateLong(domain[point.index])) +
          '" data-tt-value="' +
          compact(point.value) +
          ' MW" data-tt-sub="Energi radiasi api" />',
      )
      .join("");

    svg.innerHTML =
      '<defs><linearGradient id="' +
      svgId +
      '-fill" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="' +
      color +
      '" stop-opacity=".30" />' +
      '<stop offset="100%" stop-color="' +
      color +
      '" stop-opacity="0" />' +
      "</linearGradient></defs>" +
      grid +
      areaPaths +
      linePaths +
      dots +
      '<circle cx="' +
      peakX.toFixed(1) +
      '" cy="' +
      peakY.toFixed(1) +
      '" r="3.8" fill="' +
      color +
      '" stroke="var(--panel)" stroke-width="1.5" />' +
      '<text x="' +
      peakX.toFixed(1) +
      '" y="' +
      (peakY - 9).toFixed(1) +
      '" text-anchor="' +
      peakAnchor +
      '" fill="var(--text)" font-size="10">' +
      compact(peak.value) +
      "</text>" +
      xLabels +
      hits;

    badge.textContent =
      "Puncak hari · " +
      compact(peak.value) +
      " · " +
      dateShort(domain[peak.index]);
  }

  function renderTierChart(rows) {
    const svg = $("chart-tier");
    const badge = $("tier-peak");
    const byDate = new Map(
      (rows || []).filter((row) => row.date).map((row) => [row.date, row]),
    );

    const start = new Date(state.start + "T00:00:00");
    const end = new Date(state.end + "T00:00:00");
    const days = Math.floor((end - start) / 86400000) + 1;
    const bucketCount = Math.max(1, Math.ceil(days / 7));
    const buckets = Array.from({ length: bucketCount }, (_, index) => ({
      start: new Date(start.getTime() + index * 7 * 86400000),
      kuat: 0,
      sedang: 0,
      lemah: 0,
      kandidat: 0,
    }));

    buckets.forEach((bucket) => {
      for (let offset = 0; offset < 7; offset += 1) {
        const date = new Date(bucket.start.getTime() + offset * 86400000);
        if (date > end) break;
        const row = byDate.get(isoDate(date));
        if (!row) continue;
        bucket.kuat += Number(row.hotspot_kuat || 0);
        bucket.sedang += Number(row.hotspot_sedang || 0);
        bucket.lemah += Number(row.hotspot_lemah || 0);
        bucket.kandidat += Number(row.hotspot_kandidat || 0);
      }
    });

    const totals = buckets.map(
      (bucket) =>
        bucket.kuat + bucket.sedang + bucket.lemah + bucket.kandidat,
    );
    const peakValue = Math.max(...totals, 0);
    if (!peakValue) {
      svg.innerHTML =
        '<text x="320" y="130" text-anchor="middle" fill="var(--label)" font-size="14">Belum ada data.</text>';
      badge.textContent = "Tidak ada data";
      return;
    }

    const peakIndex = totals.indexOf(peakValue);
    const width = 640;
    const height = 260;
    const padL = 58;
    const padR = 20;
    const padT = 24;
    const padB = 38;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;
    const yMax = niceMax(peakValue * 1.08);
    const slot = plotW / buckets.length;
    const barWidth = Math.max(12, Math.min(54, slot * 0.6));

    const grid = [0, 1 / 3, 2 / 3, 1]
      .map((fraction) => {
        const y = padT + plotH - fraction * plotH;
        return (
          '<line x1="' +
          padL +
          '" y1="' +
          y.toFixed(1) +
          '" x2="' +
          (width - padR) +
          '" y2="' +
          y.toFixed(1) +
          '" stroke="var(--line)" stroke-width="1" />' +
          '<text x="' +
          (padL - 10) +
          '" y="' +
          (y + 4).toFixed(1) +
          '" text-anchor="end" fill="var(--label)" font-size="10">' +
          compact(yMax * fraction) +
          "</text>"
        );
      })
      .join("");

    const bars = buckets
      .map((bucket, index) => {
        const total =
          bucket.kuat + bucket.sedang + bucket.lemah + bucket.kandidat;
        if (!total) return "";
        const center = padL + slot * index + slot / 2;
        const x = center - barWidth / 2;
        let y = padT + plotH;
        const parts = [
          ["kuat", palette().tier.kuat],
          ["sedang", palette().tier.sedang],
          ["lemah", palette().tier.lemah],
          ["kandidat", palette().tier.kandidat],
        ]
          .map(([key, color]) => {
            const value = bucket[key];
            const barHeight = (value / yMax) * plotH;
            if (!barHeight) return "";
            y -= barHeight;
            const tierName = key.charAt(0).toUpperCase() + key.slice(1);
            const week = dateShort(isoDate(bucket.start));
            return (
              '<rect x="' +
              x.toFixed(1) +
              '" y="' +
              y.toFixed(1) +
              '" width="' +
              barWidth.toFixed(1) +
              '" height="' +
              barHeight.toFixed(1) +
              '" rx="2" fill="' +
              color +
              '" data-tt-kicker="Minggu ' +
              week +
              '" data-tt-title="' +
              tierName +
              '" data-tt-value="' +
              number.format(Math.round(value)) +
              ' hotspot" data-tt-sub="Total minggu ' +
              number.format(Math.round(total)) +
              '"></rect>'
            );
          })
          .join("");
        return parts;
      })
      .join("");

    const labels = buckets
      .map((bucket, index) => {
        if (buckets.length > 7 && index % 2 !== 0) return "";
        const center = padL + slot * index + slot / 2;
        return (
          '<text x="' +
          center.toFixed(1) +
          '" y="' +
          (height - 10) +
          '" text-anchor="middle" fill="var(--label)" font-size="10">' +
          dateShort(isoDate(bucket.start)) +
          "</text>"
        );
      })
      .join("");

    svg.innerHTML = grid + bars + labels;
    badge.textContent =
      "Puncak minggu · " +
      compact(peakValue) +
      " · " +
      dateShort(isoDate(buckets[peakIndex].start));
  }

  function treemapWorst(row, side) {
    const total = row.reduce((value, item) => value + item.area, 0);
    const maxArea = Math.max(...row.map((item) => item.area));
    const minArea = Math.min(...row.map((item) => item.area));
    return Math.max(
      (side * side * maxArea) / (total * total),
      (total * total) / (side * side * minArea),
    );
  }

  function layoutTreemap(items, x, y, width, height, out) {
    const total = items.reduce((value, item) => value + item.value, 0);
    if (!total || width <= 0 || height <= 0) return;
    const scale = (width * height) / total;
    const queue = items.map((item) => ({ ...item, area: item.value * scale }));
    const rect = { x, y, width, height };

    while (queue.length && rect.width > 0 && rect.height > 0) {
      const side = Math.min(rect.width, rect.height);
      const row = [queue[0]];
      let index = 1;
      let worst = treemapWorst(row, side);
      while (index < queue.length) {
        const candidate = row.concat(queue[index]);
        const candidateWorst = treemapWorst(candidate, side);
        if (candidateWorst > worst) break;
        row.push(queue[index]);
        worst = candidateWorst;
        index += 1;
      }
      queue.splice(0, row.length);
      const rowArea = row.reduce((value, item) => value + item.area, 0);

      if (rect.width >= rect.height) {
        const columnWidth = Math.min(rect.width, rowArea / rect.height);
        let cursorY = rect.y;
        row.forEach((item, rowIndex) => {
          const itemHeight =
            rowIndex === row.length - 1
              ? rect.y + rect.height - cursorY
              : item.area / columnWidth;
          out.push({
            ...item,
            x: rect.x,
            y: cursorY,
            width: columnWidth,
            height: itemHeight,
          });
          cursorY += itemHeight;
        });
        rect.x += columnWidth;
        rect.width -= columnWidth;
      } else {
        const rowHeight = Math.min(rect.height, rowArea / rect.width);
        let cursorX = rect.x;
        row.forEach((item, rowIndex) => {
          const itemWidth =
            rowIndex === row.length - 1
              ? rect.x + rect.width - cursorX
              : item.area / rowHeight;
          out.push({
            ...item,
            x: cursorX,
            y: rect.y,
            width: itemWidth,
            height: rowHeight,
          });
          cursorX += itemWidth;
        });
        rect.y += rowHeight;
        rect.height -= rowHeight;
      }
    }
  }

  function contrastText(hex) {
    const value = hex.replace("#", "");
    const r = parseInt(value.slice(0, 2), 16);
    const g = parseInt(value.slice(2, 4), 16);
    const b = parseInt(value.slice(4, 6), 16);
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return luminance > 0.55 ? "#1a0d03" : "#f4fbf6";
  }

  const SHORT_PROVINCE = {
    "Kalimantan Barat": "Kalbar",
    "Kalimantan Tengah": "Kalteng",
    "Kalimantan Selatan": "Kalsel",
    "Kalimantan Timur": "Kaltim",
    "Kalimantan Utara": "Kaltara",
    "Sumatera Barat": "Sumbar",
    "Sumatera Selatan": "Sumsel",
    "Sumatera Utara": "Sumut",
    "Nusa Tenggara Barat": "NTB",
    "Nusa Tenggara Timur": "NTT",
    "Kepulauan Bangka Belitung": "Babel",
    "Kepulauan Riau": "Kepri",
    "DI Yogyakarta": "DIY",
    "DKI Jakarta": "DKI",
    "Papua Barat Daya": "PBD",
    "Papua Pegunungan": "Pegunungan",
    "Papua Selatan": "Papua Sel.",
  };

  function renderTreemap(rows) {
    const svg = $("treemap");
    const note = $("treemap-note");
    const badge = $("treemap-share");
    const total = sum(rows, "hotspot_count");
    const all = [...(rows || [])]
      .filter((row) => Number(row.hotspot_count || 0) > 0)
      .sort((a, b) => Number(b.hotspot_count) - Number(a.hotspot_count));
    const top = all.slice(0, 8);

    if (!top.length) {
      svg.innerHTML =
        '<text x="500" y="170" text-anchor="middle" fill="var(--label)" font-size="14">Belum ada data.</text>';
      note.textContent = "Belum ada hotspot pada rentang ini.";
      badge.textContent = "Top 8";
      return;
    }

    const colors = palette().treemap;
    const items = top.map((row, index) => ({
      name: row.province,
      value: Number(row.hotspot_count || 0),
      color: colors[index] || colors[colors.length - 1],
    }));
    const others = all.slice(top.length);
    const othersValue = others.reduce(
      (value, row) => value + Number(row.hotspot_count || 0),
      0,
    );
    if (othersValue > 0) {
      items.push({
        name: "Lainnya · " + others.length + " provinsi",
        value: othersValue,
        color: palette().treemapOthers,
      });
    }
    const boxes = [];
    const ordered = [...items].sort((a, b) => b.value - a.value);
    layoutTreemap(ordered, 0, 0, 1000, 520, boxes);
    const topTotal = items.reduce((value, item) => value + item.value, 0);

    svg.innerHTML = boxes
      .map((box) => {
        const inset = Math.min(
          3,
          Math.max(1, Math.min(box.width, box.height) * 0.08),
        );
        const x = box.x + inset;
        const y = box.y + inset;
        const width = Math.max(0, box.width - inset * 2);
        const height = Math.max(0, box.height - inset * 2);
        const fill = contrastText(box.color);
        const rawName = box.name;
        const narrow = width < 115;
        const labelName = narrow
          ? SHORT_PROVINCE[rawName] || rawName
          : rawName;
        const name =
          labelName.length > 20 ? labelName.slice(0, 19) + "…" : labelName;
        const fontSize = narrow ? 17 : 21;
        const showName = width > 88 && height > 64;
        const showInline = !showName && width > 180 && height > 30;
        const showValue =
          !showName && !showInline && width > 70 && height > 34;
        const maxChars = Math.max(
          5,
          Math.floor((width - 18) / (fontSize * 0.53)),
        );
        const words = labelName.split(" ");
        const lines = [];
        let currentLine = words[0] || "";
        for (let wordIndex = 1; wordIndex < words.length; wordIndex += 1) {
          const candidate = currentLine + " " + words[wordIndex];
          if (candidate.length <= maxChars) {
            currentLine = candidate;
          } else {
            lines.push(currentLine);
            currentLine = words[wordIndex];
          }
        }
        lines.push(currentLine);
        const labelLines = lines.slice(0, 2);
        if (labelLines.length === 2 && labelLines[1].length > maxChars) {
          labelLines[1] = labelLines[1].slice(0, maxChars - 1) + "…";
        }
        const labelSvg = labelLines
          .map(
            (lineText, lineIndex) =>
              '<tspan x="' +
              (x + 9).toFixed(1) +
              '" y="' +
              (y + 26 + lineIndex * 22).toFixed(1) +
              '">' +
              lineText +
              "</tspan>",
          )
          .join("");
        const valueY = y + 26 + (labelLines.length - 1) * 22 + 22;
        const share = (box.value / topTotal) * 100;
        const labelText =
          box.name +
          ": " +
          number.format(box.value) +
          " hotspot (" +
          decimal.format(share) +
          "%)";
        return (
          '<g class="treemap-tile" tabindex="0" role="img" aria-label="' +
          escapeText(labelText) +
          '" data-tt-kicker="Provinsi" data-tt-title="' +
          escapeText(box.name) +
          '" data-tt-value="' +
          number.format(box.value) +
          ' hotspot" data-tt-sub="' +
          decimal.format(share) +
          '% dari total">' +
          '<rect x="' +
          x.toFixed(1) +
          '" y="' +
          y.toFixed(1) +
          '" width="' +
          width.toFixed(1) +
          '" height="' +
          height.toFixed(1) +
          '" rx="4" fill="' +
          box.color +
          '" opacity=".94"></rect>' +
          (showName
            ? '<text fill="' +
              fill +
              '" font-size="' +
              fontSize +
              '" font-weight="600">' +
              labelSvg +
              "</text>" +
              '<text x="' +
              (x + 9).toFixed(1) +
              '" y="' +
              valueY.toFixed(1) +
              '" fill="' +
              fill +
              '" opacity=".82" font-size="' +
              (narrow ? 14 : 15) +
              '">' +
              number.format(box.value) +
              "</text>"
            : "") +
          (showInline
            ? '<text x="' +
              (x + 9).toFixed(1) +
              '" y="' +
              (y + 24).toFixed(1) +
              '" fill="' +
              fill +
              '" font-size="17">' +
              name +
              " · " +
              number.format(box.value) +
              "</text>"
            : "") +
          (showValue
            ? '<text x="' +
              (x + 9).toFixed(1) +
              '" y="' +
              (y + 24).toFixed(1) +
              '" fill="' +
              fill +
              '" opacity=".84" font-size="16">' +
              number.format(box.value) +
              "</text>"
            : "") +
          "</g>"
        );
      })
      .join("");

    badge.textContent = "Top " + top.length + " + lainnya";
    note.textContent =
      top.length +
      " provinsi teratas + " +
      others.length +
      " lainnya · " +
      decimal.format((topTotal / total) * 100) +
      "% dari total hotspot";
  }

  function heatColor(ratio) {
    const ramp = palette().heat;
    if (ratio <= 0.001) return ramp[0];
    if (ratio < 0.25) return ramp[1];
    if (ratio < 0.5) return ramp[2];
    if (ratio < 0.75) return ramp[3];
    if (ratio < 0.9) return ramp[4];
    return ramp[5];
  }

  function renderDailyStrip(rows) {
    const host = $("day-strip");
    const badge = $("strip-peak");
    const byDate = new Map(
      (rows || []).map((row) => [row.date, Number(row.hotspot_count || 0)]),
    );
    const start = new Date(state.start + "T00:00:00");
    const end = new Date(state.end + "T00:00:00");
    const dates = [];
    const cursor = new Date(start);
    while (cursor <= end) {
      dates.push(isoDate(cursor));
      cursor.setDate(cursor.getDate() + 1);
    }

    if (!dates.length) {
      host.innerHTML = '<p class="dash-empty">Tidak ada tanggal.</p>';
      badge.textContent = "—";
      return;
    }

    const values = dates
      .filter((date) => byDate.has(date))
      .map((date) => byDate.get(date));
    const maxValue = Math.max(...values, 0);
    const peakDate = dates.find((date) => byDate.get(date) === maxValue);

    host.innerHTML = dates
      .map((date) => {
        const day = new Date(date + "T00:00:00").getDate();
        if (!byDate.has(date)) {
          return (
            '<div class="day-cell empty" tabindex="0" data-tt-kicker="Kalender hotspot" data-tt-title="' +
            escapeText(dateLong(date)) +
            '" data-tt-value="Tidak ada data" data-tt-sub="Tidak ada sel pada tanggal ini" aria-label="' +
            escapeText(dateLong(date)) +
            ': tidak ada data">' +
            day +
            "</div>"
          );
        }
        const value = byDate.get(date);
        const [background, color] = heatColor(maxValue ? value / maxValue : 0);
        return (
          '<div class="day-cell" tabindex="0" style="background:' +
          background +
          ";color:" +
          color +
          '" data-tt-kicker="Kalender hotspot" data-tt-title="' +
          escapeText(dateLong(date)) +
          '" data-tt-value="' +
          number.format(value) +
          ' hotspot" data-tt-sub="Intensitas harian" aria-label="' +
          escapeText(dateLong(date)) +
          ": " +
          number.format(value) +
          ' hotspot">' +
          day +
          "</div>"
        );
      })
      .join("");

    badge.textContent = maxValue
      ? "Puncak " + compact(maxValue) + " · " + dateShort(peakDate)
      : "Tidak ada data";
  }

  function renderTop(hostId, rows, key, gold, total) {
    const host = $(hostId);
    const sorted = [...(rows || [])]
      .filter((row) => Number(row[key] || 0) > 0)
      .sort((a, b) => Number(b[key]) - Number(a[key]))
      .slice(0, 5);

    if (!sorted.length) {
      host.innerHTML =
        '<p class="dash-empty">Belum ada data pada rentang ini.</p>';
      return;
    }

    const denominator = Number(total) || 1;
    host.innerHTML = sorted
      .map((row, index) => {
        const numeric = Number(row[key] || 0);
        const share = (numeric / denominator) * 100;
        const width = Math.max(1.5, share);
        return (
          '<div class="rank-row">' +
          '<span class="rank-no">' +
          String(index + 1).padStart(2, "0") +
          "</span>" +
          '<span class="rank-name" title="' +
          row.province +
          " \u00b7 " +
          number.format(Math.round(numeric)) +
          " \u00b7 " +
          decimal.format(share) +
          '%">' +
          row.province +
          "</span>" +
          '<span class="rank-val">' +
          number.format(Math.round(numeric)) +
          "<small>" +
          decimal.format(share) +
          "%</small></span>" +
          '<span class="rank-track' +
          (gold ? " gold" : "") +
          '"><i style="width:' +
          width.toFixed(1) +
          '%"></i></span>' +
          "</div>"
        );
      })
      .join("");
  }

  // Batas kepulauan: Natural Earth 1:110m (domain publik), diproyeksikan
  // ke viewBox peta 640x320.
  const ISLAND_PATHS =
    "M365.5 284.0 L360.4 284.3 L344.6 273.3 L355.7 270.2 L362.0 275.0 L366.2 279.8 L365.5 284.0 Z" +
    "M410.0 282.4 L399.7 285.9 L398.3 284.0 L399.4 278.7 L404.5 269.0 L416.3 262.8 L417.5 265.9 L417.8 270.7 L410.0 282.4 Z" +
    "M331.8 250.2 L336.1 254.4 L343.5 253.1 L346.5 259.8 L332.6 263.0 L324.4 265.1 L317.9 265.0 L322.0 255.9 L328.6 255.8 L331.8 250.2 Z" +
    "M391.6 250.2 L389.9 258.9 L371.9 263.4 L356.0 261.5 L356.0 255.7 L365.5 252.4 L373.0 257.2 L380.9 256.0 L391.6 250.2 Z" +
    "M220.9 229.4 L243.8 231.0 L246.4 224.5 L268.6 232.1 L273.0 242.3 L290.9 245.2 L305.6 254.6 L291.9 260.6 L278.8 254.2 L267.9 254.6 L255.5 253.5 L244.3 250.6 L230.5 244.6 L221.7 243.1 L216.7 245.0 L194.9 238.5 L192.9 231.8 L181.9 230.6 L190.1 215.5 L204.6 216.5 L214.3 222.6 L219.2 223.8 L220.9 229.4 Z" +
    "M533.0 220.6 L526.8 231.3 L525.7 219.4 L527.8 213.8 L530.3 208.4 L533.0 213.0 L533.0 220.6 Z" +
    "M443.6 177.1 L439.1 182.4 L430.9 179.5 L428.5 172.7 L440.6 171.9 L443.6 177.1 Z" +
    "M482.1 171.4 L486.5 183.4 L476.4 176.9 L466.4 175.6 L459.6 176.6 L451.4 176.1 L454.2 167.4 L469.0 166.8 L482.1 171.4 Z" +
    "M526.0 140.7 L529.4 166.2 L541.8 175.7 L551.8 159.0 L565.5 149.4 L576.1 149.4 L586.3 154.9 L595.2 160.6 L608.0 163.6 L608.2 215.0 L608.4 266.3 L597.8 253.4 L585.7 250.2 L582.7 254.7 L567.6 255.2 L572.6 242.4 L580.2 238.0 L577.0 220.8 L571.3 207.6 L548.1 194.3 L538.3 192.9 L520.3 178.4 L516.8 186.0 L512.2 187.4 L509.5 181.6 L509.4 174.8 L500.3 167.1 L513.2 161.4 L521.7 161.7 L520.7 157.5 L503.2 157.5 L498.5 148.1 L487.8 145.2 L482.7 137.4 L498.8 133.6 L505.0 128.4 L524.2 134.9 L526.0 140.7 Z" +
    "M419.6 100.2 L410.0 115.8 L401.0 118.9 L389.5 115.8 L369.6 116.6 L359.1 118.8 L357.4 130.8 L368.1 144.8 L374.6 137.7 L396.9 132.3 L395.9 139.6 L390.7 137.3 L385.5 146.5 L375.0 152.6 L386.3 172.8 L384.1 178.2 L394.8 196.4 L394.7 206.8 L388.3 211.4 L383.7 205.9 L389.4 193.0 L377.7 199.1 L374.7 194.7 L376.3 188.6 L367.7 179.4 L368.5 164.0 L360.6 168.8 L361.6 187.2 L362.1 209.7 L354.5 212.0 L349.3 207.4 L352.8 192.9 L350.9 177.7 L345.9 177.6 L342.2 166.8 L347.1 156.4 L348.8 143.9 L354.8 120.2 L357.3 113.7 L367.5 101.9 L376.8 106.6 L391.9 108.8 L405.7 108.1 L417.5 96.7 L419.6 100.2 Z" +
    "M460.8 104.7 L460.2 118.5 L454.0 117.0 L452.2 126.6 L457.1 134.9 L453.8 136.8 L449.0 126.8 L445.4 106.6 L447.8 94.0 L451.8 88.3 L452.6 96.9 L459.7 98.3 L460.8 104.7 Z" +
    "M331.5 93.8 L344.9 108.4 L330.8 110.2 L326.8 121.0 L327.3 135.3 L315.8 146.0 L315.5 161.7 L310.9 185.8 L309.1 180.2 L295.5 187.3 L290.8 177.7 L282.2 176.8 L276.3 171.8 L262.1 177.4 L257.7 169.8 L249.9 170.7 L240.0 168.8 L238.2 147.7 L232.2 143.3 L226.5 129.8 L224.8 116.0 L226.2 101.4 L233.3 91.0 L235.3 101.5 L243.5 110.4 L251.2 107.2 L258.8 108.3 L265.8 100.4 L271.5 99.0 L282.8 103.4 L292.6 100.0 L298.7 78.1 L303.3 72.6 L307.5 54.7 L321.2 54.7 L331.6 57.4 L324.8 71.6 L333.6 86.5 L331.5 93.8 Z" +
    "M187.3 214.8 L174.1 215.2 L164.0 202.0 L148.7 189.1 L143.5 179.6 L134.5 166.7 L128.5 154.9 L119.4 132.8 L108.9 119.7 L105.4 106.1 L101.0 93.8 L90.2 83.9 L84.0 70.4 L75.0 61.6 L62.5 44.2 L61.5 36.2 L69.2 36.8 L87.7 39.9 L98.2 55.3 L107.5 66.0 L114.1 72.5 L125.4 89.5 L137.6 89.7 L147.6 100.5 L154.5 113.7 L163.7 120.9 L158.9 133.8 L165.7 139.3 L170.0 139.7 L172.0 150.7 L176.2 159.5 L185.0 160.9 L190.8 170.9 L187.8 190.5 L187.3 214.8 Z";

  function renderMap(rows, summaryRows) {
    const svg = $("map-hotspot");
    const total = sum(summaryRows, "hotspot_count");
    const top = [...(summaryRows || [])].sort(
      (a, b) => Number(b.hotspot_count) - Number(a.hotspot_count),
    )[0];

    $("map-date").textContent = dateLong(state.end);
    $("map-count").textContent = String(rows.length >= 500 ? 500 : rows.length);
    $("map-provinces").textContent = String((summaryRows || []).length);
    $("map-dominant").textContent =
      top ? SHORT_PROVINCE[top.province] || top.province : "—";
    $("map-dominant-share").textContent =
      top && total
        ? decimal.format((Number(top.hotspot_count) / total) * 100) + "%"
        : "";
    const byProvince = new Map(
      (summaryRows || []).map((row) => [row.province, row]),
    );
    const defaultProvince = top ? top.province : "";
    const setFocus = (province) => {
      const row = byProvince.get(province) || top;
      $("map-focus-name").textContent = row ? row.province : "—";
      $("map-focus-hotspot").textContent = row
        ? number.format(Math.round(Number(row.hotspot_count)))
        : "—";
      $("map-focus-share").textContent =
        row && total
          ? decimal.format((Number(row.hotspot_count) / total) * 100) + "%"
          : "—";
    };
    setFocus(defaultProvince);

    const colors = palette();
    const land =
      '<rect width="640" height="320" fill="url(#mapGrid)" />' +
      '<g fill="' +
      colors.mapLand +
      '" stroke="' +
      colors.mapStroke +
      '" stroke-width="1.3" stroke-linejoin="round">' +
      '<path fill-rule="evenodd" d="' +
      ISLAND_PATHS +
      '" />' +
      "</g>" +
      '<g fill="' +
      colors.mapLabel +
      '" font-size="9.5" font-weight="600" letter-spacing="1.2" text-anchor="middle" opacity=".8">' +
      '<text x="95" y="223">SUMATERA</text><text x="235" y="260">JAWA</text><text x="338" y="206">KALIMANTAN</text><text x="440" y="218">SULAWESI</text><text x="568" y="216">PAPUA</text>' +
      "</g>";

    if (!rows.length) {
      svg.innerHTML =
        '<defs><pattern id="mapGrid" width="26" height="26" patternUnits="userSpaceOnUse"><path d="M 26 0 L 0 0 0 26" fill="none" stroke="' +
        colors.mapGrid +
        '" stroke-width="1" /></pattern></defs>' +
        land +
        '<text x="320" y="168" text-anchor="middle" fill="var(--label)" font-size="13">Tidak ada sel pada tanggal ini.</text>';
      return;
    }

    const maxCount = Math.max(
      ...rows.map((row) => Number(row.hotspot_count || 0)),
      1,
    );
    const project = (lat, lon) => [
      46 + ((Number(lon) - 94) / 48) * 574,
      28 + ((6 - Number(lat)) / 17) * 268,
    ];
    const color = (row) => {
      if (Number(row.hotspot_kuat) > 0) return colors.tier.kuat;
      if (Number(row.hotspot_sedang) > 0) return colors.tier.sedang;
      if (Number(row.hotspot_lemah) > 0) return colors.tier.lemah;
      return colors.tier.kandidat;
    };
    const radius = (count) =>
      Math.min(7, Math.max(1.6, 1.4 + Math.sqrt(count) * 0.42));

    const topCells = [...rows]
      .sort((a, b) => Number(b.hotspot_count) - Number(a.hotspot_count))
      .slice(0, 6);
    const glows = topCells
      .map((row) => {
        const [x, y] = project(row.cell_lat, row.cell_lon);
        return (
          '<circle class="map-glow" cx="' +
          x.toFixed(1) +
          '" cy="' +
          y.toFixed(1) +
          '" r="' +
          (radius(Number(row.hotspot_count)) + 4).toFixed(1) +
          '" fill="' +
          color(row) +
          '" opacity=".13" />'
        );
      })
      .join("");

    const dots = rows
      .map((row) => {
        const count = Number(row.hotspot_count || 0);
        const [x, y] = project(row.cell_lat, row.cell_lon);
        if (x < 8 || x > 632 || y < 8 || y > 312) return "";
        const opacity = 0.3 + 0.55 * (count / maxCount);
        return (
          '<circle class="map-dot" data-province="' +
          escapeText(row.province) +
          '" data-tt-kicker="Sel hotspot" data-tt-title="' +
          escapeText(row.province) +
          '" data-tt-value="' +
          number.format(count) +
          ' hotspot" data-tt-sub="Klik untuk fokus provinsi" aria-label="' +
          escapeText(row.province) +
          ": " +
          number.format(count) +
          '" cx="' +
          x.toFixed(1) +
          '" cy="' +
          y.toFixed(1) +
          '" r="' +
          radius(count).toFixed(1) +
          '" fill="' +
          color(row) +
          '" opacity="' +
          opacity.toFixed(2) +
          '"></circle>'
        );
      })
      .join("");

    svg.innerHTML =
      '<defs><pattern id="mapGrid" width="26" height="26" patternUnits="userSpaceOnUse"><path d="M 26 0 L 0 0 0 26" fill="none" stroke="' +
      colors.mapGrid +
      '" stroke-width="1" /></pattern></defs>' +
      land +
      glows +
      dots;

    svg.querySelectorAll(".map-dot").forEach((dot) => {
      const province = dot.dataset.province;
      dot.addEventListener("pointerenter", (event) => {
        if (event.pointerType === "touch") return;
        dot.classList.add("is-focus");
        setFocus(province);
      });
      dot.addEventListener("pointerleave", (event) => {
        if (event.pointerType === "touch") return;
        dot.classList.remove("is-focus");
        setFocus(defaultProvince);
      });
      dot.addEventListener("click", () => setFocus(province));
    });
  }

  function renderDonut(summaryRows) {
    const svg = $("donut");
    const legend = $("donut-legend");
    const colors = palette().tier;
    const segments = [
      { label: "Kuat", value: sum(summaryRows, "hotspot_kuat"), color: colors.kuat },
      { label: "Sedang", value: sum(summaryRows, "hotspot_sedang"), color: colors.sedang },
      { label: "Lemah", value: sum(summaryRows, "hotspot_lemah"), color: colors.lemah },
      { label: "Kandidat", value: sum(summaryRows, "hotspot_kandidat"), color: colors.kandidat },
    ].filter((segment) => segment.value > 0);

    const total = segments.reduce((acc, segment) => acc + segment.value, 0);
    if (!total) {
      svg.innerHTML =
        '<text x="100" y="105" text-anchor="middle" fill="var(--label)" font-size="13">Belum ada data.</text>';
      legend.innerHTML = "";
      return;
    }

    const radius = 72;
    const circumference = 2 * Math.PI * radius;
    let offset = 0;
    const circles = segments
      .map((segment) => {
        const length = (segment.value / total) * circumference;
        const share = (segment.value / total) * 100;
        const circle =
          '<circle class="donut-seg" tabindex="0" cx="100" cy="100" r="' +
          radius +
          '" fill="none" stroke="' +
          segment.color +
          '" stroke-width="22" stroke-dasharray="' +
          length.toFixed(2) +
          " " +
          circumference.toFixed(2) +
          '" stroke-dashoffset="' +
          (-offset).toFixed(2) +
          '" data-tt-kicker="Tingkat bukti" data-tt-title="' +
          segment.label +
          '" data-tt-value="' +
          number.format(segment.value) +
          ' hotspot" data-tt-sub="' +
          decimal.format(share) +
          '% dari total" aria-label="' +
          segment.label +
          ": " +
          number.format(segment.value) +
          ' hotspot, ' +
          decimal.format(share) +
          '% dari total" />';
        offset += length;
        return circle;
      })
      .join("");

    svg.innerHTML =
      '<circle cx="100" cy="100" r="' +
      radius +
      '" fill="none" stroke="var(--line-soft)" stroke-width="22" />' +
      '<g transform="rotate(-90 100 100)">' +
      circles +
      "</g>" +
      '<text x="100" y="97" text-anchor="middle" fill="var(--text)" font-size="21" font-weight="600">' +
      compact(total) +
      "</text>" +
      '<text x="100" y="115" text-anchor="middle" fill="var(--label)" font-size="10">hotspot</text>';

    legend.innerHTML = segments
      .map(
        (segment) =>
          '<div class="donut-item"><i style="background:' +
          segment.color +
          '"></i>' +
          segment.label +
          "<b>" +
          number.format(segment.value) +
          "<small>" +
          decimal.format((segment.value / total) * 100) +
          "%</small></b></div>",
      )
      .join("");
  }

  function renderFreshness(health) {
    const iceberg = health.iceberg || {};
    const latest = dateLong(health.latest_date);
    const age = Number(iceberg.age_hours);
    const stale = Boolean(iceberg.stale);
    const status = $("freshness");
    const wrapper = status.parentElement;

    let text = "Data " + latest + " · Iceberg ";
    if (iceberg.status === "ok" && Number.isFinite(age)) {
      text += (stale ? "stale" : "segar") + " · " + decimal.format(age) + " jam";
    } else {
      text += "belum dipublish";
    }
    status.textContent = text;
    wrapper.classList.toggle("warn", stale && iceberg.status === "ok");
    wrapper.classList.toggle(
      "bad",
      iceberg.status !== "ok" && iceberg.status !== "missing",
    );
  }

  async function load() {
    hideError();
    setLoading(true);
    try {
      const cellParams = new URLSearchParams({
        date: state.end,
        limit: "500",
      });
      if (state.province) cellParams.set("province", state.province);
      const cellsUrl = "/cells/hotspots?" + cellParams.toString();
      const [summary, daily, monthly, health, cells] = await Promise.all([
        getJson("/hotspots/summary?" + query()),
        getJson("/hotspots/daily/total?" + query({ limit: "1000" })),
        getJson("/burn-scar/monthly?" + scarQuery()),
        getJson("/health"),
        getJson(cellsUrl).catch(() => ({ rows: [] })),
      ]);

      const summaryRows = summary.rows || [];
      const dailyRows = daily.rows || [];
      const startMonth = state.start.slice(0, 7);
      const endMonth = state.end.slice(0, 7);
      const monthlyRows = (monthly.rows || []).filter(
        (row) => row.burn_month >= startMonth && row.burn_month <= endMonth,
      );

      lastData = {
        summaryRows,
        dailyRows,
        monthlyRows,
        health,
        cells: cells.rows || [],
      };
      renderAll(lastData);
    } catch (error) {
      showError("Data belum bisa dimuat. " + error.message);
      $("freshness").textContent = "Data gagal dimuat";
    } finally {
      setLoading(false);
    }
  }

  async function loadProvinces() {
    try {
      const payload = await getJson("/meta/provinces");
      const select = $("dash-province");
      (payload.provinces || []).forEach((province) => {
        const option = document.createElement("option");
        option.value = province;
        option.textContent = province;
        select.appendChild(option);
      });
    } catch (_) {
      /* Daftar provinsi opsional; filter tetap bisa memakai "semua". */
    }
  }

  function applyFilters() {
    const start = $("dash-start").value;
    const end = $("dash-end").value;
    if (!start || !end || start > end) {
      showError("Rentang tanggal tidak valid.");
      return;
    }
    state.start = start;
    state.end = end;
    state.province = $("dash-province").value;
    load();
  }

  function bindFilters() {
    $("dash-filter").addEventListener("submit", (event) => {
      event.preventDefault();
      applyFilters();
    });
  }

  const TABS = ["sebaran", "tren"];

  function activateTab(id, focus, updateHash) {
    const next = TABS.includes(id) ? id : "sebaran";
    TABS.forEach((key) => {
      const tab = $("tab-" + key);
      const panel = $("panel-" + key);
      const active = key === next;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      panel.hidden = !active;
    });
    if (focus) $("tab-" + next).focus();
    if (updateHash) history.replaceState(null, "", "#" + next);
  }

  function bindTabs() {
    const tabs = [...document.querySelectorAll(".dash-tab")];
    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        activateTab(tab.dataset.tab, false, true);
      });
      tab.addEventListener("keydown", (event) => {
        const index = TABS.indexOf(tab.dataset.tab);
        let next = null;
        if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
        if (event.key === "ArrowLeft")
          next = (index - 1 + TABS.length) % TABS.length;
        if (event.key === "Home") next = 0;
        if (event.key === "End") next = TABS.length - 1;
        if (next === null) return;
        event.preventDefault();
        activateTab(TABS[next], true, true);
      });
    });
    window.addEventListener("hashchange", () => {
      activateTab(location.hash.slice(1), false, false);
    });
    activateTab(location.hash.slice(1), false, false);
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindTheme();
    bindTooltips();
    bindTabs();
    bindFilters();
    loadProvinces();
    load();
  });
})();
