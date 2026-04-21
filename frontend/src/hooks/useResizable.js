// src/hooks/useResizable.js
// Hook quản lý logic kéo thả để resize hai panel
import { useState, useRef, useEffect, useCallback } from 'react'

export function useResizable({
  defaultLeftPercent = 60,
  minLeftPercent = 25,
  maxLeftPercent = 80,
} = {}) {
  const [leftPercent, setLeftPercent] = useState(defaultLeftPercent)
  const isDragging = useRef(false)
  const containerRef = useRef(null)

  const handleMouseDown = useCallback((e) => {
    e.preventDefault()
    isDragging.current = true
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
  }, [])

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (!isDragging.current || !containerRef.current) return
      const rect = containerRef.current.getBoundingClientRect()
      const newPercent = ((e.clientX - rect.left) / rect.width) * 100
      if (newPercent >= minLeftPercent && newPercent <= maxLeftPercent) {
        setLeftPercent(newPercent)
      }
    }

    const handleMouseUp = () => {
      if (!isDragging.current) return
      isDragging.current = false
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [minLeftPercent, maxLeftPercent])

  return { leftPercent, containerRef, handleMouseDown, isDragging }
}