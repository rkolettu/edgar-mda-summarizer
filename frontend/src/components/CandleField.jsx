import { useEffect, useRef } from 'react'

// A slowly turning 3D field of tiny candlestick glyphs, drawn on a canvas. 'rings' fills the landing hero; 'funnel'
// is the cone behind the closing call to action. Decorative only: it pauses offscreen and holds still for reduced motion.

function mulberry32(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function rotate([x, y, z], ax, ay) {
  const cy = Math.cos(ay), sy = Math.sin(ay)
  const x1 = x * cy + z * sy
  const z1 = -x * sy + z * cy
  const cx = Math.cos(ax), sx = Math.sin(ax)
  return [x1, y * cx - z1 * sx, y * sx + z1 * cx]
}

function ringsPoints(rand) {
  const pts = []
  // Tilted rings of different sizes around a shared centre, plus a loose shell of scattered glyphs.
  const rings = [
    { r: 1.0, n: 150, tilt: [0.35, 0.2], off: [0, 0, 0] },
    { r: 0.78, n: 120, tilt: [1.2, -0.4], off: [0, 0, 0] },
    { r: 0.55, n: 90, tilt: [-0.6, 0.9], off: [0, 0, 0] },
    { r: 0.32, n: 70, tilt: [1.45, 0.1], off: [-0.35, -0.2, 0.1] },
    { r: 0.24, n: 60, tilt: [0.2, 1.3], off: [0.75, 0.45, -0.2] },
  ]
  for (const ring of rings) {
    for (let i = 0; i < ring.n; i++) {
      const a = (i / ring.n) * Math.PI * 2
      const jitter = 1 + (rand() - 0.5) * 0.04
      const p = rotate([Math.cos(a) * ring.r * jitter, Math.sin(a) * ring.r * jitter, 0], ring.tilt[0], ring.tilt[1])
      pts.push([p[0] + ring.off[0], p[1] + ring.off[1], p[2] + ring.off[2]])
    }
  }
  for (let i = 0; i < 260; i++) {
    const u = rand() * 2 - 1
    const t = rand() * Math.PI * 2
    const r = 1.15 + rand() * 0.35
    const s = Math.sqrt(1 - u * u)
    pts.push([Math.cos(t) * s * r, u * r * 0.8, Math.sin(t) * s * r])
  }
  return pts
}

function funnelPoints(rand) {
  const pts = []
  // A cone opening upward (screen y grows downward), with a spiral that winds down to its tip.
  for (let i = 0; i < 420; i++) {
    const h = Math.sqrt(rand())  // denser toward the wide rim
    const a = rand() * Math.PI * 2
    pts.push([Math.cos(a) * h * 0.95, 0.9 - h * 1.8, Math.sin(a) * h * 0.95])
  }
  for (let i = 0; i < 160; i++) {
    const h = i / 160
    const a = h * Math.PI * 7
    pts.push([Math.cos(a) * h * 0.8, 0.9 - h * 1.8, Math.sin(a) * h * 0.8])
  }
  return pts
}

export default function CandleField({ shape = 'rings', className = '', color = '23, 23, 23', speed = 1, seed = 7 }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!ctx) return

    const rand = mulberry32(seed)
    const points = (shape === 'funnel' ? funnelPoints : ringsPoints)(rand).map((p) => ({
      p,
      kind: rand(),        // candle, T, inverted T or a small block
      wick: 0.5 + rand(),  // relative wick length
      body: 0.25 + rand() * 0.6,
      filled: rand() > 0.55,
      phase: rand() * Math.PI * 2,
    }))

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let width = 0, height = 0, dpr = 1
    let frame = 0, visible = true, start = performance.now()
    const pointer = { x: 0, y: 0, tx: 0, ty: 0 }

    function resize() {
      const rect = canvas.getBoundingClientRect()
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      width = rect.width
      height = rect.height
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    function draw(now) {
      const t = (now - start) / 1000
      pointer.x += (pointer.tx - pointer.x) * 0.05
      pointer.y += (pointer.ty - pointer.y) * 0.05
      ctx.clearRect(0, 0, width, height)
      const scale = Math.min(width, height) * (shape === 'funnel' ? 0.5 : 0.42)
      const cx = width / 2, cy = height / 2
      const ay = t * 0.12 * speed + pointer.x * 0.5
      const ax = (shape === 'funnel' ? 0.35 : 0.25) + Math.sin(t * 0.07 * speed) * 0.12 + pointer.y * 0.3
      const glyph = Math.max(3.5, Math.min(width, height) / 110)

      for (const pt of points) {
        const [x, y, z] = rotate(pt.p, ax, ay)
        const persp = 3 / (3 + z)
        const sx = cx + x * scale * persp
        const sy = cy + y * scale * persp
        if (sx < -10 || sx > width + 10 || sy < -10 || sy > height + 10) continue
        const depth = (1 - z) / 2  // nearer glyphs are darker
        const alpha = Math.max(0.08, Math.min(0.85, 0.15 + depth * 0.6))
        const g = glyph * persp
        // Candles breathe a little, like a live chart.
        const wick = g * (1.4 + pt.wick * 0.9) * (1 + Math.sin(t * 1.3 + pt.phase) * 0.12)
        ctx.fillStyle = `rgba(${color}, ${alpha})`
        ctx.strokeStyle = `rgba(${color}, ${alpha})`
        ctx.lineWidth = Math.max(0.6, persp * 0.9)
        ctx.beginPath()
        if (pt.kind < 0.5) {
          ctx.moveTo(sx, sy - wick / 2)
          ctx.lineTo(sx, sy + wick / 2)
          ctx.stroke()
          const bh = wick * pt.body
          if (pt.filled) ctx.fillRect(sx - g * 0.32, sy - bh / 2, g * 0.64, bh)
          else ctx.strokeRect(sx - g * 0.3, sy - bh / 2, g * 0.6, bh)
        } else if (pt.kind < 0.8) {
          const top = pt.kind < 0.65 ? -1 : 1  // T or ⊥
          ctx.moveTo(sx, sy - wick / 2)
          ctx.lineTo(sx, sy + wick / 2)
          ctx.moveTo(sx - g * 0.45, sy + (top * wick) / 2)
          ctx.lineTo(sx + g * 0.45, sy + (top * wick) / 2)
          ctx.stroke()
        } else {
          ctx.fillStyle = `rgba(${color}, ${alpha * 0.55})`
          ctx.fillRect(sx - g * 0.35, sy - g * 0.35, g * 0.7, g * 0.7 * (0.8 + pt.body))
        }
      }
    }

    function loop(now) {
      draw(now)
      if (visible && !reduced) frame = requestAnimationFrame(loop)
    }

    function onPointer(e) {
      const rect = canvas.getBoundingClientRect()
      pointer.tx = ((e.clientX - rect.left) / rect.width - 0.5) * 0.6
      pointer.ty = ((e.clientY - rect.top) / rect.height - 0.5) * 0.6
    }

    resize()
    draw(start + 4000)
    const resizeObserver = new ResizeObserver(() => {
      resize()
      if (reduced) draw(start + 4000)
    })
    resizeObserver.observe(canvas)
    const intersection = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting
      cancelAnimationFrame(frame)
      if (visible && !reduced) frame = requestAnimationFrame(loop)
    })
    intersection.observe(canvas)
    if (!reduced) window.addEventListener('pointermove', onPointer, { passive: true })

    return () => {
      cancelAnimationFrame(frame)
      resizeObserver.disconnect()
      intersection.disconnect()
      window.removeEventListener('pointermove', onPointer)
    }
  }, [shape, color, speed, seed])

  return <canvas ref={canvasRef} aria-hidden="true" className={`pointer-events-none ${className}`} />
}
