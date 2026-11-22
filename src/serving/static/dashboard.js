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
    const progress = $("dash-progress");
    if (progress) progress.hidden = !loading;
    const wrap = document.querySelector(".dash-wrap");
    if (wrap) wrap.setAttribute("aria-busy", String(loading));
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

    $("tabs-period").textContent = periodLabel();
    $("rail-period").textContent = periodLabel();
    $("rail-coverage").textContent = provinceCount + " provinsi";
    $("rail-total").textContent = number.format(total);
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
          ["kuat", "#E2402A"],
          ["sedang", "#F2711C"],
          ["lemah", "#E9A21B"],
          ["kandidat", "#2F5E49"],
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

    const colors = [
      "#D9581E",
      "#1B4F36",
      "#266044",
      "#317054",
      "#3D8062",
      "#4F9070",
      "#65A184",
      "#7FB29A",
    ];
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
        color: "#B7AF9F",
      });
    }
    const boxes = [];
    layoutTreemap(items, 0, 0, 1000, 570, true, boxes);
    const topTotal = items.reduce((value, item) => value + item.value, 0);

    svg.innerHTML = boxes
      .map((box) => {
        const x = box.x + 3;
        const y = box.y + 3;
        const width = Math.max(0, box.width - 6);
        const height = Math.max(0, box.height - 6);
        const fill = contrastText(box.color);
        const rawName = box.name;
        const name =
          rawName.length > 20 ? rawName.slice(0, 19) + "…" : rawName;
        const showName = width > 115 && height > 74;
        const showInline = !showName && width > 180 && height > 30;
        const showValue =
          !showName && !showInline && width > 70 && height > 34;
        const maxChars = Math.max(6, Math.floor((width - 18) / (21 * 0.53)));
        const words = rawName.split(" ");
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
          '" opacity=".94"><title>' +
          box.name +
          ": " +
          number.format(box.value) +
          " hotspot (" +
          decimal.format((box.value / topTotal) * 100) +
          "%)</title></rect>" +
          (showName
            ? '<text fill="' +
              fill +
              '" font-size="21" font-weight="600">' +
              labelSvg +
              "</text>" +
              '<text x="' +
              (x + 9).toFixed(1) +
              '" y="' +
              valueY.toFixed(1) +
              '" fill="' +
              fill +
              '" opacity=".82" font-size="15">' +
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
    if (ratio <= 0.001) return ["#f1ede2", "#8a978c"];
    if (ratio < 0.25) return ["#e6efe5", "#3f5c4c"];
    if (ratio < 0.5) return ["#c7ddc6", "#24402f"];
    if (ratio < 0.75) return ["#9dc79b", "#16241c"];
    if (ratio < 0.9) return ["#ffb02e", "#1a0d03"];
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
      '<g fill="#dce5c9" stroke="#a8b996" stroke-width="1.3" stroke-linejoin="round">' +
      '<path fill-rule="evenodd" d="' +
      ISLAND_PATHS +
      '" />' +
      "</g>" +
      '<g fill="#6d7f72" font-size="9.5" font-weight="600" letter-spacing="1.4" text-anchor="middle" opacity=".85">' +
      '<text x="95" y="223">SUMATERA</text><text x="235" y="260">JAWA</text><text x="338" y="206">KALIMANTAN</text><text x="440" y="218">SULAWESI</text><text x="568" y="216">PAPUA</text>' +
      "</g>";

    if (!rows.length) {
      svg.innerHTML =
        '<defs><pattern id="mapGrid" width="26" height="26" patternUnits="userSpaceOnUse"><path d="M 26 0 L 0 0 0 26" fill="none" stroke="#e6dfd1" stroke-width="1" /></pattern></defs>' +
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
      if (Number(row.hotspot_kuat) > 0) return "#E2402A";
      if (Number(row.hotspot_sedang) > 0) return "#F2711C";
      if (Number(row.hotspot_lemah) > 0) return "#E9A21B";
      return "#2F5E49";
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
      '<defs><pattern id="mapGrid" width="26" height="26" patternUnits="userSpaceOnUse"><path d="M 26 0 L 0 0 0 26" fill="none" stroke="#e6dfd1" stroke-width="1" /></pattern></defs>' +
      land +
      glows +
      dots;
  }

  function renderDonut(summaryRows) {
    const svg = $("donut");
    const legend = $("donut-legend");
    const segments = [
      { label: "Kuat", value: sum(summaryRows, "hotspot_kuat"), color: "#E2402A" },
      { label: "Sedang", value: sum(summaryRows, "hotspot_sedang"), color: "#F2711C" },
      { label: "Lemah", value: sum(summaryRows, "hotspot_lemah"), color: "#E9A21B" },
      { label: "Kandidat", value: sum(summaryRows, "hotspot_kandidat"), color: "#2F5E49" },
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
        "#D9581E",
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
    } catch (error) {
      console.error("Dashboard load failed", error);
      showError(
        "Data belum bisa dimuat. Coba lagi sebentar atau periksa koneksi API serving.",
      );
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
    const tabs = [...document.querySelectorAll(".side-tab, .dash-tab")];
    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        activateTab(tab.dataset.tab, false, true);
      });
      tab.addEventListener("keydown", (event) => {
        const index = TABS.indexOf(tab.dataset.tab);
        let next = null;
        if (event.key === "ArrowRight" || event.key === "ArrowDown")
          next = (index + 1) % TABS.length;
        if (event.key === "ArrowLeft" || event.key === "ArrowUp")
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
