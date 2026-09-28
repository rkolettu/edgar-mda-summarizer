import { useEffect, useRef } from 'react'

// A loose 3D cloud of tiny candlestick glyphs drawn on a canvas. Every visit scatters it differently: glyphs gather
// in a few soft clumps, each drifts on its own path, flickers at its own pace and wraps around the edges, while the
// whole cloud turns slowly and leans toward the pointer. Decorative only: it pauses offscreen and holds still for
// reduced motion.

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

const BOX = { x: 1.35, y: 1.05, z: 1 }  // half-extents of the space the glyphs drift through

// Muted up and down colors, drawn faintly so the cloud stays in the background.
const UP = '40, 130, 90'
const DOWN = '190, 70, 64'

function gaussian(rand) {
  return Math.sqrt(-2 * Math.log(1 - rand())) * Math.cos(2 * Math.PI * rand())
}

// Two in five glyphs scattered anywhere, the rest in a handful of soft clumps placed at random.
function scatter(rand) {
  const clumps = Array.from({ length: 5 + Math.floor(rand() * 4) }, () => ({
    c: [(rand() * 2 - 1) * BOX.x * 0.8, (rand() * 2 - 1) * BOX.y * 0.8, (rand() * 2 - 1) * BOX.z * 0.8],
    r: 0.12 + rand() * 0.3,
  }))
  return Array.from({ length: 620 }, () => {
    if (rand() < 0.4) return [(rand() * 2 - 1) * BOX.x, (rand() * 2 - 1) * BOX.y, (rand() * 2 - 1) * BOX.z]
    const { c, r } = clumps[Math.floor(rand() * clumps.length)]
    return [c[0] + gaussian(rand) * r * 1.4, c[1] + gaussian(rand) * r, c[2] + gaussian(rand) * r]
  })
}

// Wraps a coordinate into [-half, half].
function wrap(v, half) {
  const span = half * 2
  return ((((v + half) % span) + span) % span) - half
}

export default function CandleField({ className = '', color = '23, 23, 23', speed = 1, seed }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!ctx) return

    const rand = mulberry32(seed ?? Math.floor(Math.random() * 2 ** 31))
    const points = scatter(rand).map((p) => {
      const heading = rand() * Math.PI * 2
      const drift = 0.03 + rand() * 0.07
      return {
        p,
        v: [Math.cos(heading) * drift, Math.sin(heading) * drift * 0.6, (rand() - 0.5) * drift],
        kind: rand(),              // candle, T, inverted T or a small block
        size: 0.55 + rand() * 1.1,
        wick: 0.5 + rand(),        // relative wick length
        body: 0.25 + rand() * 0.6,
        filled: rand() > 0.45,
        tone: rand(),              // up, down or neutral
        phase: rand() * Math.PI * 2,
        pulse: 0.4 + rand() * 1.6, // breathing speed
        twinkle: 0.2 + rand() * 0.9,
      }
    })

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
      const scale = Math.min(width, height) * 0.4
      const cx = width / 2, cy = height / 2
      const ay = t * 0.04 * speed + pointer.x * 0.5
      const ax = 0.2 + Math.sin(t * 0.05 * speed) * 0.08 + pointer.y * 0.3
      const glyph = Math.max(3.5, Math.min(width, height) / 110)

      for (const pt of points) {
        const local = [
          wrap(pt.p[0] + pt.v[0] * t * speed + Math.sin(t * 0.3 + pt.phase) * 0.02, BOX.x),
          wrap(pt.p[1] + pt.v[1] * t * speed + Math.cos(t * 0.25 + pt.phase) * 0.02, BOX.y),
          wrap(pt.p[2] + pt.v[2] * t * speed, BOX.z),
        ]
        // Fade out near the edges of the box, so wrapping around never pops.
        const edge = Math.min(BOX.x - Math.abs(local[0]), BOX.y - Math.abs(local[1]), BOX.z - Math.abs(local[2]))
        const fade = Math.min(1, edge / 0.18)
        if (fade <= 0.02) continue
        const [x, y, z] = rotate(local, ax, ay)
        const persp = 3 / (3 + z)
        const sx = cx + x * scale * persp
        const sy = cy + y * scale * persp
        if (sx < -10 || sx > width + 10 || sy < -10 || sy > height + 10) continue
        const depth = (1 - z) / 2  // nearer glyphs are darker
        const flicker = 0.75 + Math.sin(t * pt.twinkle + pt.phase * 2) * 0.25
        const alpha = Math.max(0.05, Math.min(0.85, (0.12 + depth * 0.6) * flicker * fade))
        const g = glyph * persp * pt.size
        // Candles tick like a live chart: the wick breathes and the body grows, shrinks and slides along it.
        const wick = g * (1.4 + pt.wick * 0.9) * (1 + Math.sin(t * pt.pulse + pt.phase) * 0.14)
        const rgb = pt.tone < 0.42 ? UP : pt.tone < 0.78 ? DOWN : color
        const a = pt.tone < 0.78 ? alpha * 0.8 : alpha
        ctx.fillStyle = `rgba(${rgb}, ${a})`
        ctx.strokeStyle = `rgba(${rgb}, ${a})`
        ctx.lineWidth = Math.max(0.6, persp * 0.9)
        ctx.beginPath()
        if (pt.kind < 0.55) {
          ctx.moveTo(sx, sy - wick / 2)
          ctx.lineTo(sx, sy + wick / 2)
          ctx.stroke()
          const bh = wick * pt.body * (0.65 + Math.sin(t * pt.pulse * 1.3 + pt.phase) * 0.35)
          const by = sy - bh / 2 + Math.sin(t * pt.pulse * 0.8 + pt.phase * 3) * (wick - bh) * 0.4
          if (pt.filled) ctx.fillRect(sx - g * 0.32, by, g * 0.64, bh)
          else ctx.strokeRect(sx - g * 0.3, by, g * 0.6, bh)
        } else if (pt.kind < 0.85) {
          const top = pt.kind < 0.7 ? -1 : 1  // T or ⊥
          ctx.moveTo(sx, sy - wick / 2)
          ctx.lineTo(sx, sy + wick / 2)
          ctx.moveTo(sx - g * 0.45, sy + (top * wick) / 2)
          ctx.lineTo(sx + g * 0.45, sy + (top * wick) / 2)
          ctx.stroke()
        } else {
          ctx.fillStyle = `rgba(${rgb}, ${a * 0.55})`
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
  }, [color, speed, seed])

  return <canvas ref={canvasRef} aria-hidden="true" className={`pointer-events-none ${className}`} />
}
