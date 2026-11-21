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
    const params = new URLSearchParams({
      month: state.start.slice(0, 7),
      limit: "1000",
    });
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

    $("kpi-total").textContent = number.format(total);
    $("kpi-total-sub").textContent =
      periodLabel() + " · " + provinceCount + " provinsi";

    $("kpi-kuat").textContent = number.format(kuat);
    $("kpi-kuat-sub").textContent = total
      ? decimal.format((kuat / total) * 100) + "% dari total hotspot"
      : "Tidak ada hotspot pada rentang ini";

    $("kpi-frp").textContent = decimal.format(frp / 1_000_000) + " jt";
    $("kpi-frp-sub").textContent = "MW · puncak " + number.format(frpMax) + " MW";

    $("kpi-scar").textContent = number.format(Math.round(scar));
    $("kpi-scar-sub").textContent =
      "km² · " + number.format(scarPixels) + " piksel MCD64A1";

    $("period-label").textContent = "Dashboard · " + periodLabel();
    $("filter-period").textContent = periodLabel();
    $("scar-period").textContent =
      monthLong(state.start.slice(0, 7)) + " · km²";
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
        '<text x="320" y="130" text-anchor="middle" fill="var(--label)" font-size="14">Belum ada data.</text>';
      badge.textContent = "Tidak ada data";
      return;
    }

    const width = 640;
    const height = 260;
    const padL = 58;
    const padR = 20;
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
          '" text-anchor="end" fill="var(--label)" font-size="11">' +
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
          '" fill="var(--label)" font-size="11">' +
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
      '" fill="var(--text)" font-size="11">' +
      compact(peak.value) +
      "</text>" +
      xLabels;

    badge.textContent =
      "Puncak " + compact(peak.value) + " · " + dateShort(domain[peak.index]);
  }

  function renderTop(hostId, rows, key, gold) {
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
      .map((row) => {
        const value = Math.max(2, (Number(row[key]) / biggest) * 100);
        return (
          '<div class="rank-row">' +
          '<span class="rank-name" title="' +
          row.province +
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

  function renderDonut(summaryRows) {
    const svg = $("donut");
    const legend = $("donut-legend");
    const segments = [
      { label: "Kuat", value: sum(summaryRows, "hotspot_kuat"), color: "#EAF3EC" },
      { label: "Sedang", value: sum(summaryRows, "hotspot_sedang"), color: "#A9C6B6" },
      { label: "Lemah", value: sum(summaryRows, "hotspot_lemah"), color: "#6F8E7E" },
      { label: "Kandidat", value: sum(summaryRows, "hotspot_kandidat"), color: "#46604F" },
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
          decimal.format((segment.value / total) * 100) +
          "%</b></div>",
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
      const [summary, daily, monthly, health] = await Promise.all([
        getJson("/hotspots/summary?" + query()),
        getJson("/hotspots/daily/total?" + query({ limit: "1000" })),
        getJson("/burn-scar/monthly?" + scarQuery()),
        getJson("/health"),
      ]);

      renderSummary(summary.rows || [], monthly.rows || []);
      renderLineChart(
        "chart-hotspot",
        daily.rows || [],
        "hotspot_count",
        "hotspot-peak",
        "#ff8a3d",
      );
      renderLineChart(
        "chart-frp",
        daily.rows || [],
        "frp_sum",
        "frp-peak",
        "#ffb02e",
      );
      renderTop("top-hotspot", summary.rows || [], "hotspot_count", false);
      renderTop("top-scar", monthly.rows || [], "scar_area_km2", true);
      renderDonut(summary.rows || []);
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

    document.querySelectorAll("[data-range]").forEach((button) => {
      button.addEventListener("click", () => {
        document
          .querySelectorAll("[data-range]")
          .forEach((item) => item.classList.toggle("on", item === button));
        $("dash-start").value = button.dataset.start;
        $("dash-end").value = button.dataset.end;
        state.start = button.dataset.start;
        state.end = button.dataset.end;
        state.province = $("dash-province").value;
        load();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindFilters();
    loadProvinces();
    load();
  });
})();
