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

  function renderSummary(summaryRows, monthlyRows) {
    const total = sum(summaryRows, "hotspot_count");
    const kuat = sum(summaryRows, "hotspot_kuat");
    const frp = sum(summaryRows, "frp_sum");
    const frpMax = max(summaryRows, "frp_max");
    const scar = sum(monthlyRows, "scar_area_km2");
    const scarPixels = sum(monthlyRows, "scar_pixels");
    const provinceCount = (summaryRows || []).length;

    $("tab1-total").textContent = number.format(total);
    $("tab1-total-sub").textContent =
      periodLabel() + " \u00b7 " + provinceCount + " provinsi";

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

    $("tab1-period").textContent = periodLabel();
    $("tab2-period").textContent = periodLabel();
    $("period-label").textContent = "Dashboard \u00b7 " + periodLabel();
    $("filter-meta").textContent =
      provinceCount + " provinsi \u00b7 " + number.format(total) + " hotspot";
    $("scar-period").textContent =
      scarPeriodLabel(monthlyRows) + " \u00b7 km\u00b2";
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
    $("tab2-frp-sub").textContent = "Σ MW · gabungan provinsi";

    $("tab2-frp-date").textContent = frpPeak
      ? dateShort(frpPeak.date)
      : "\u2014";
    $("tab2-frp-date-sub").textContent = "puncak FRP";
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
      xLabels;

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
          ["kuat", "#ff5a2b"],
          ["sedang", "#ff8a3d"],
          ["lemah", "#ffb02e"],
          ["kandidat", "#315e49"],
        ]
          .map(([key, color]) => {
            const value = bucket[key];
            const barHeight = (value / yMax) * plotH;
            if (!barHeight) return "";
            y -= barHeight;
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
              '"><title>' +
              key +
              ": " +
              number.format(Math.round(value)) +
              "</title></rect>"
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

  function layoutTreemap(items, x, y, width, height, vertical, out) {
    if (items.length === 1) {
      out.push({ ...items[0], x, y, width, height });
      return;
    }
    const total = items.reduce((value, item) => value + item.value, 0);
    let accumulated = 0;
    let split = 1;
    for (let index = 0; index < items.length - 1; index += 1) {
      accumulated += items[index].value;
      if (accumulated >= total / 2) {
        split = index + 1;
        break;
      }
    }
    const left = items.slice(0, split);
    const right = items.slice(split);
    const leftTotal = left.reduce((value, item) => value + item.value, 0);
    const ratio = leftTotal / total;
    if (vertical) {
      layoutTreemap(left, x, y, width * ratio, height, !vertical, out);
      layoutTreemap(right, x + width * ratio, y, width * (1 - ratio), height, !vertical, out);
    } else {
      layoutTreemap(left, x, y, width, height * ratio, !vertical, out);
      layoutTreemap(right, x, y + height * ratio, width, height * (1 - ratio), !vertical, out);
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

  function renderTreemap(rows) {
    const svg = $("treemap");
    const note = $("treemap-note");
    const badge = $("treemap-share");
    const total = sum(rows, "hotspot_count");
    const top = [...(rows || [])]
      .filter((row) => Number(row.hotspot_count || 0) > 0)
      .sort((a, b) => Number(b.hotspot_count) - Number(a.hotspot_count))
      .slice(0, 8);

    if (!top.length) {
      svg.innerHTML =
        '<text x="500" y="170" text-anchor="middle" fill="var(--label)" font-size="14">Belum ada data.</text>';
      note.textContent = "Belum ada hotspot pada rentang ini.";
      badge.textContent = "Top 8";
      return;
    }

    const colors = [
      "#ff5a2b",
      "#ff7a2d",
      "#ff9a3d",
      "#ffb02e",
      "#e0a03a",
      "#c98a35",
      "#a87532",
      "#8a6230",
    ];
    const items = top.map((row, index) => ({
      name: row.province,
      value: Number(row.hotspot_count || 0),
      color: colors[index] || colors[colors.length - 1],
    }));
    const boxes = [];
    layoutTreemap(items, 0, 0, 1000, 340, true, boxes);
    const topTotal = items.reduce((value, item) => value + item.value, 0);

    svg.innerHTML = boxes
      .map((box) => {
        const x = box.x + 3;
        const y = box.y + 3;
        const width = Math.max(0, box.width - 6);
        const height = Math.max(0, box.height - 6);
        const fill = contrastText(box.color);
        const name =
          box.name.length > 20 ? box.name.slice(0, 19) + "…" : box.name;
        const showName = width > 105 && height > 46;
        const showInline = !showName && width > 180 && height > 30;
        const showValue =
          !showName && !showInline && width > 70 && height > 34;
        return (
          '<g><rect x="' +
          x.toFixed(1) +
          '" y="' +
          y.toFixed(1) +
          '" width="' +
          width.toFixed(1) +
          '" height="' +
          height.toFixed(1) +
          '" rx="4" fill="' +
          box.color +
          '" opacity=".92"><title>' +
          box.name +
          ": " +
          number.format(box.value) +
          " hotspot (" +
          decimal.format((box.value / topTotal) * 100) +
          "%)</title></rect>" +
          (showName
            ? '<text x="' +
              (x + 9).toFixed(1) +
              '" y="' +
              (y + 20).toFixed(1) +
              '" fill="' +
              fill +
              '" font-size="14" font-weight="600">' +
              name +
              "</text>" +
              '<text x="' +
              (x + 9).toFixed(1) +
              '" y="' +
              (y + 39).toFixed(1) +
              '" fill="' +
              fill +
              '" opacity=".84" font-size="11">' +
              number.format(box.value) +
              "</text>"
            : "") +
          (showInline
            ? '<text x="' +
              (x + 9).toFixed(1) +
              '" y="' +
              (y + 21).toFixed(1) +
              '" fill="' +
              fill +
              '" font-size="11">' +
              name +
              " · " +
              number.format(box.value) +
              "</text>"
            : "") +
          (showValue
            ? '<text x="' +
              (x + 9).toFixed(1) +
              '" y="' +
              (y + 22).toFixed(1) +
              '" fill="' +
              fill +
              '" opacity=".84" font-size="11">' +
              number.format(box.value) +
              "</text>"
            : "") +
          "</g>"
        );
      })
      .join("");

    badge.textContent = "Top " + top.length;
    note.textContent =
      top.length +
      " provinsi · " +
      decimal.format((topTotal / total) * 100) +
      "% dari total hotspot";
  }

  function heatColor(ratio) {
    if (ratio <= 0.001) return ["#173026", "#eaf3ec"];
    if (ratio < 0.25) return ["#2f5e49", "#f4fbf6"];
    if (ratio < 0.5) return ["#6f9c83", "#10241c"];
    if (ratio < 0.75) return ["#ffb02e", "#1a0d03"];
    if (ratio < 0.9) return ["#ff8a3d", "#1a0d03"];
    return ["#ff5a2b", "#1a0d03"];
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
            '<div class="day-cell empty" tabindex="0" title="' +
            dateLong(date) +
            ': tidak ada data" aria-label="' +
            dateLong(date) +
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
          '" title="' +
          dateLong(date) +
          ": " +
          number.format(value) +
          ' hotspot" aria-label="' +
          dateLong(date) +
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
      host.innerHTML = '<p class="dash-empty">Belum ada data pada rentang ini.</p>';
      return;
    }

    const biggest = Math.max(...sorted.map((row) => Number(row[key] || 0)), 1);
    host.innerHTML = sorted
      .map((row, index) => {
        const value = Math.max(2, (Number(row[key]) / biggest) * 100);
        const share =
          total && Number(total) > 0
            ? decimal.format((Number(row[key]) / Number(total)) * 100)
            : null;
        return (
          '<div class="rank-row">' +
          '<span class="rank-no">' +
          String(index + 1).padStart(2, "0") +
          "</span>" +
          '<span class="rank-name" title="' +
          row.province +
          " · " +
          number.format(Math.round(Number(row[key] || 0))) +
          (share !== null ? " · " + share + "%" : "") +
          '">' +
          row.province +
          "</span>" +
          '<span class="rank-val">' +
          number.format(Math.round(Number(row[key] || 0))) +
          "</span>" +
          '<span class="rank-track' +
          (gold ? " gold" : "") +
          '"><i style="width:' +
          value.toFixed(1) +
          '%"></i></span>' +
          "</div>"
        );
      })
      .join("");
  }

  function renderMap(rows, summaryRows) {
    const svg = $("map-hotspot");
    const total = sum(summaryRows, "hotspot_count");
    const top = [...(summaryRows || [])].sort(
      (a, b) => Number(b.hotspot_count) - Number(a.hotspot_count),
    )[0];

    $("map-date").textContent = dateLong(state.end);
    $("map-count").textContent =
      rows.length >= 500 ? "500 sel teratas" : rows.length + " sel";
    $("map-focus-name").textContent = top ? top.province : "—";
    $("map-focus-hotspot").textContent = top
      ? number.format(Math.round(Number(top.hotspot_count)))
      : "—";
    $("map-focus-share").textContent =
      top && total
        ? decimal.format((Number(top.hotspot_count) / total) * 100) + "%"
        : "—";

    const land =
      '<rect width="640" height="320" fill="url(#mapGrid)" />' +
      '<g fill="#1a3a2a" stroke="#35604a" stroke-width="1.3">' +
      '<path d="M80 55 L115 70 L130 100 L120 130 L145 165 L138 198 L118 208 L102 180 L92 148 L75 112 L65 80 Z" />' +
      '<path d="M150 225 L195 220 L245 228 L295 220 L320 230 L300 240 L245 243 L195 238 L160 237 Z" />' +
      '<path d="M270 75 L315 60 L365 70 L400 95 L408 130 L388 165 L355 185 L320 188 L288 165 L270 130 Z" />' +
      '<path d="M420 80 L438 70 L450 95 L442 120 L462 148 L452 180 L438 196 L425 178 L432 150 L416 125 L412 100 Z" />' +
      '<path d="M505 120 L550 100 L590 105 L625 125 L635 155 L615 180 L580 195 L545 185 L515 165 L500 140 Z" />' +
      '<circle cx="340" cy="250" r="3.5" /><circle cx="365" cy="255" r="3" /><circle cx="390" cy="252" r="3.5" /><circle cx="415" cy="248" r="3" />' +
      "</g>" +
      '<g fill="#9ab5a5" font-size="10" text-anchor="middle" opacity=".82">' +
      '<text x="95" y="223">Sumatera</text><text x="235" y="260">Jawa</text><text x="338" y="206">Kalimantan</text><text x="440" y="218">Sulawesi</text><text x="568" y="216">Papua</text>' +
      "</g>";

    if (!rows.length) {
      svg.innerHTML =
        '<defs><pattern id="mapGrid" width="26" height="26" patternUnits="userSpaceOnUse"><path d="M 26 0 L 0 0 0 26" fill="none" stroke="#173026" stroke-width="1" /></pattern></defs>' +
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
      if (Number(row.hotspot_kuat) > 0) return "#ff5a2b";
      if (Number(row.hotspot_sedang) > 0) return "#ff8a3d";
      if (Number(row.hotspot_lemah) > 0) return "#ffb02e";
      return "#6f9c83";
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
          '<circle cx="' +
          x.toFixed(1) +
          '" cy="' +
          y.toFixed(1) +
          '" r="' +
          radius(count).toFixed(1) +
          '" fill="' +
          color(row) +
          '" opacity="' +
          opacity.toFixed(2) +
          '"><title>' +
          row.province +
          ": " +
          number.format(count) +
          " hotspot</title></circle>"
        );
      })
      .join("");

    svg.innerHTML =
      '<defs><pattern id="mapGrid" width="26" height="26" patternUnits="userSpaceOnUse"><path d="M 26 0 L 0 0 0 26" fill="none" stroke="#173026" stroke-width="1" /></pattern></defs>' +
      land +
      glows +
      dots;
  }

  function renderDonut(summaryRows) {
    const svg = $("donut");
    const legend = $("donut-legend");
    const segments = [
      { label: "Kuat", value: sum(summaryRows, "hotspot_kuat"), color: "#ff5a2b" },
      { label: "Sedang", value: sum(summaryRows, "hotspot_sedang"), color: "#ff8a3d" },
      { label: "Lemah", value: sum(summaryRows, "hotspot_lemah"), color: "#ffb02e" },
      { label: "Kandidat", value: sum(summaryRows, "hotspot_kandidat"), color: "#315e49" },
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
        const circle =
          '<circle cx="100" cy="100" r="' +
          radius +
          '" fill="none" stroke="' +
          segment.color +
          '" stroke-width="22" stroke-dasharray="' +
          length.toFixed(2) +
          " " +
          circumference.toFixed(2) +
          '" stroke-dashoffset="' +
          (-offset).toFixed(2) +
          '" />';
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

  function renderScarSummary(rows) {
    const km2 = sum(rows, "scar_area_km2");
    const pixels = sum(rows, "scar_pixels");
    const provinces = new Set(
      (rows || []).map((row) => row.province).filter(Boolean),
    ).size;
    const hasData = (rows || []).length > 0;

    $("scar-total-km2").textContent = hasData
      ? number.format(Math.round(km2))
      : "—";
    $("scar-total-pixels").textContent = hasData
      ? number.format(Math.round(pixels))
      : "—";
    $("scar-provinces").textContent = provinces || "—";
    $("scar-total-badge").textContent = hasData
      ? number.format(Math.round(km2)) + " km²"
      : "Belum ada";
    $("scar-summary-period").textContent =
      scarPeriodLabel(rows) + " · km²";
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

      renderSummary(summaryRows, monthlyRows);
      renderTrendKpis(dailyRows);
      renderTierChart(dailyRows);
      renderDailyStrip(dailyRows);
      renderMap(cells.rows || [], summaryRows);
      renderTreemap(summaryRows);
      renderLineChart(
        "chart-frp",
        dailyRows,
        "frp_sum",
        "frp-peak",
        "#ffb02e",
      );
      renderTop(
        "top-hotspot",
        summaryRows,
        "hotspot_count",
        false,
        sum(summaryRows, "hotspot_count"),
      );
      renderTop(
        "top-scar",
        monthlyRows,
        "scar_area_km2",
        true,
        sum(monthlyRows, "scar_area_km2"),
      );
      renderDonut(summaryRows);
      renderScarSummary(monthlyRows);

      const hotspotTotal = sum(summaryRows, "hotspot_count");
      const scarTotal = sum(monthlyRows, "scar_area_km2");
      const kandidat = sum(summaryRows, "hotspot_kandidat");
      $("top-hotspot-note").textContent = summaryRows.length
        ? summaryRows.length +
          " provinsi · " +
          number.format(hotspotTotal) +
          " hotspot"
        : "Belum ada data pada rentang ini.";
      $("top-scar-note").textContent = monthlyRows.length
        ? "Total " +
          number.format(Math.round(scarTotal)) +
          " km² · " +
          scarPeriodLabel(monthlyRows)
        : "Belum ada data scar bulan ini.";
      $("donut-note").textContent = hotspotTotal
        ? "Kandidat " +
          decimal.format((kandidat / hotspotTotal) * 100) +
          "% dari total"
        : "Belum ada data pada rentang ini.";

      renderFreshness(health);
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

  const TABS = ["ikhtisar", "tren", "prediksi"];

  function activateTab(id, focus, updateHash) {
    const next = TABS.includes(id) ? id : "ikhtisar";
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
    bindTabs();
    bindFilters();
    loadProvinces();
    load();
  });
})();
