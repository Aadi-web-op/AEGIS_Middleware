/**
 * GraphField – animated, interactive evidence-network canvas for the hero.
 *
 * Nodes drift slowly; nearby nodes link. Signal pulses travel along links.
 * The cursor pulls nearby nodes in and lights up their connections.
 * Node colours match the Decision Graph legend (decision / claim / evidence /
 * document / reason), so the hero previews the real product.
 * Pauses when off-screen or the tab is hidden; static under reduced motion.
 */
import { useEffect, useRef } from "react";
import { prefersReducedMotion } from "./useMotion.js";

const TYPES = [
  { color: "#4a9eff", r: 4.2, weight: 1 }, // decision
  { color: "#22c55e", r: 3.2, weight: 3 }, // claim
  { color: "#7dd3fc", r: 2.8, weight: 5 }, // evidence
  { color: "#c084fc", r: 3.6, weight: 2 }, // document
  { color: "#f472b6", r: 2.6, weight: 1 }, // reason
  { color: "#2dd4bf", r: 2.4, weight: 4 }, // brand
];
const WEIGHTED = TYPES.flatMap((t) => Array(t.weight).fill(t));

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return `${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`;
}

export default function GraphField({ density = 1 }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    const reduced = prefersReducedMotion();
    let w = 0;
    let h = 0;
    let dpr = 1;
    let nodes = [];
    let pulses = [];
    let raf = 0;
    let running = true;
    const mouse = { x: -9999, y: -9999, active: false };
    const LINK = 150;

    function build() {
      const rect = canvas.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = rect.width;
      h = rect.height;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const count = Math.round(Math.min(120, (w * h) / 11000) * density);
      nodes = Array.from({ length: count }, () => {
        const t = WEIGHTED[Math.floor(Math.random() * WEIGHTED.length)];
        return {
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.25,
          vy: (Math.random() - 0.5) * 0.25,
          r: t.r,
          color: t.color,
          rgb: hexToRgb(t.color),
          phase: Math.random() * Math.PI * 2,
        };
      });
      pulses = [];
    }

    function spawnPulse() {
      if (nodes.length < 2) return;
      const a = nodes[Math.floor(Math.random() * nodes.length)];
      let best = null;
      let bestD = LINK;
      for (const b of nodes) {
        if (b === a) continue;
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        if (d < bestD && d > 30) {
          bestD = d;
          best = b;
        }
      }
      if (best) pulses.push({ a, b: best, t: 0, speed: 0.012 + Math.random() * 0.012 });
    }

    function frame(time) {
      ctx.clearRect(0, 0, w, h);

      // Move
      for (const n of nodes) {
        if (!reduced) {
          n.x += n.vx;
          n.y += n.vy;
          if (n.x < -20) n.x = w + 20;
          if (n.x > w + 20) n.x = -20;
          if (n.y < -20) n.y = h + 20;
          if (n.y > h + 20) n.y = -20;
          if (mouse.active) {
            const dx = mouse.x - n.x;
            const dy = mouse.y - n.y;
            const d = Math.hypot(dx, dy);
            if (d < 180 && d > 1) {
              n.x += (dx / d) * 0.35;
              n.y += (dy / d) * 0.35;
            }
          }
        }
      }

      // Links
      ctx.lineWidth = 1;
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j];
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d < LINK) {
            const alpha = (1 - d / LINK) * 0.22;
            ctx.strokeStyle = `rgba(148,163,184,${alpha})`;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
        if (mouse.active) {
          const d = Math.hypot(a.x - mouse.x, a.y - mouse.y);
          if (d < 180) {
            ctx.strokeStyle = `rgba(45,212,191,${(1 - d / 180) * 0.5})`;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(mouse.x, mouse.y);
            ctx.stroke();
          }
        }
      }

      // Pulses travelling along links
      if (!reduced && Math.random() < 0.08) spawnPulse();
      pulses = pulses.filter((p) => p.t <= 1);
      for (const p of pulses) {
        p.t += p.speed;
        const x = p.a.x + (p.b.x - p.a.x) * p.t;
        const y = p.a.y + (p.b.y - p.a.y) * p.t;
        const g = ctx.createRadialGradient(x, y, 0, x, y, 8);
        g.addColorStop(0, `rgba(${p.a.rgb},0.95)`);
        g.addColorStop(1, `rgba(${p.a.rgb},0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(x, y, 8, 0, Math.PI * 2);
        ctx.fill();
      }

      // Nodes
      for (const n of nodes) {
        const pulse = reduced ? 1 : 1 + Math.sin(time / 900 + n.phase) * 0.18;
        const r = n.r * pulse;
        ctx.fillStyle = `rgba(${n.rgb},0.14)`;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r * 3, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = n.color;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fill();
      }

      if (running && !reduced) raf = requestAnimationFrame(frame);
    }

    function start() {
      cancelAnimationFrame(raf);
      running = true;
      raf = requestAnimationFrame(frame);
    }
    function stop() {
      running = false;
      cancelAnimationFrame(raf);
    }

    build();
    start();

    const onResize = () => {
      build();
      if (reduced) frame(0);
    };
    const onMove = (e) => {
      const rect = canvas.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;
      mouse.active = mouse.y >= 0 && mouse.y <= rect.height;
    };
    const onLeave = () => {
      mouse.active = false;
    };
    const onVisibility = () => (document.hidden ? stop() : start());

    const io = new IntersectionObserver(([e]) => (e.isIntersecting ? start() : stop()));
    io.observe(canvas);

    window.addEventListener("resize", onResize);
    window.addEventListener("pointermove", onMove);
    document.addEventListener("pointerleave", onLeave);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      io.disconnect();
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [density]);

  return <canvas ref={canvasRef} className="graph-field" aria-hidden="true" />;
}
