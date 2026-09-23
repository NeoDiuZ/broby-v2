import { useEffect, useRef, useState } from 'react'
import { Pause, Play } from 'lucide-react'

export const VideoPlayer = ({ src }) => {
  const videoRef = useRef(null)
  const containerRef = useRef(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [showControls, setShowControls] = useState(false)
  const [progress, setProgress] = useState(0)
  const [isVisible, setIsVisible] = useState(false)
  const [hoverProgress, setHoverProgress] = useState(null)
  const [isHoveringProgress, setIsHoveringProgress] = useState(false)
  const hideControlsTimeoutRef = useRef(null)

  // Intersection Observer - only play when fully visible
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && entry.intersectionRatio >= 0.95) {
            // 95% or more is visible
            setIsVisible(true)
          } else {
            setIsVisible(false)
            if (videoRef.current) {
              videoRef.current.pause()
              setIsPlaying(false)
            }
          }
        })
      },
      {
        threshold: [0, 0.25, 0.5, 0.75, 0.95, 1.0],
      }
    )

    if (containerRef.current) {
      observer.observe(containerRef.current)
    }

    return () => {
      if (containerRef.current) {
        observer.unobserve(containerRef.current)
      }
    }
  }, [])

  // Auto-play when visible
  useEffect(() => {
    if (isVisible && videoRef.current) {
      videoRef.current.play().catch(err => {
        console.log('Autoplay prevented:', err)
      })
      setIsPlaying(true)
    }
  }, [isVisible])

  // Update progress bar
  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    const updateProgress = () => {
      const progress = (video.currentTime / video.duration) * 100
      setProgress(progress)
    }

    video.addEventListener('timeupdate', updateProgress)
    return () => video.removeEventListener('timeupdate', updateProgress)
  }, [])

  // Handle play/pause
  const togglePlayPause = () => {
    const video = videoRef.current
    if (!video) return

    if (video.paused) {
      video.play()
      setIsPlaying(true)
      setShowControls(false)
    } else {
      video.pause()
      setIsPlaying(false)
      setShowControls(true)

      // Hide controls after 1 second
      if (hideControlsTimeoutRef.current) {
        clearTimeout(hideControlsTimeoutRef.current)
      }
      hideControlsTimeoutRef.current = setTimeout(() => {
        setShowControls(false)
      }, 1000)
    }
  }

  // Handle progress bar click
  const handleProgressClick = (e) => {
    const video = videoRef.current
    if (!video) return

    const rect = e.currentTarget.getBoundingClientRect()
    const pos = (e.clientX - rect.left) / rect.width
    video.currentTime = pos * video.duration
  }

  // Handle progress bar hover
  const handleProgressMouseMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const pos = (e.clientX - rect.left) / rect.width
    setHoverProgress(pos * 100)
  }

  const handleProgressMouseEnter = () => {
    setIsHoveringProgress(true)
  }

  const handleProgressMouseLeave = () => {
    setIsHoveringProgress(false)
    setHoverProgress(null)
  }

  // Format time for tooltip
  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  // Show controls on hover
  const handleMouseEnter = () => {
    setShowControls(true)
    if (hideControlsTimeoutRef.current) {
      clearTimeout(hideControlsTimeoutRef.current)
    }
  }

  const handleMouseLeave = () => {
    if (!isPlaying) {
      // Keep controls visible if paused
      return
    }
    setShowControls(false)
  }

  return (
    <div
      ref={containerRef}
      className="relative w-full cursor-pointer group"
      style={{ paddingBottom: '56.25%' }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <video
        ref={videoRef}
        src={src}
        className="absolute inset-0 w-full h-full object-cover rounded-lg"
        loop
        muted
        playsInline
        onClick={togglePlayPause}
        preload="metadata"
        loading="lazy"
      />

      {/* Pause/Play Button Overlay */}
      <div
        className={`absolute inset-0 flex items-center justify-center pointer-events-none transition-opacity duration-300 ${
          showControls ? 'opacity-100' : 'opacity-0'
        }`}
      >
        <button
          onClick={togglePlayPause}
          className="pointer-events-auto bg-black/50 hover:bg-black/70 text-white rounded-full p-4 transition-all"
        >
          {isPlaying ? <Pause className="w-8 h-8" /> : <Play className="w-8 h-8" />}
        </button>
      </div>

      {/* Progress Bar */}
      <div
        className={`absolute bottom-0 left-0 right-0 bg-gray-300/50 cursor-pointer transition-all duration-300 ${
          showControls || !isPlaying ? 'opacity-100' : 'opacity-0'
        } group-hover:opacity-100 ${isHoveringProgress ? 'h-2' : 'h-1'}`}
        onClick={handleProgressClick}
        onMouseMove={handleProgressMouseMove}
        onMouseEnter={handleProgressMouseEnter}
        onMouseLeave={handleProgressMouseLeave}
      >
        {/* Progress fill */}
        <div
          className="h-full bg-primary transition-all"
          style={{ width: `${progress}%` }}
        />

        {/* Hover scrubber */}
        {isHoveringProgress && hoverProgress !== null && (
          <>
            {/* Hover line */}
            <div
              className="absolute top-0 bottom-0 w-0.5 bg-white shadow-lg"
              style={{ left: `${hoverProgress}%` }}
            />

            {/* Time tooltip */}
            <div
              className="absolute -top-10 transform -translate-x-1/2 bg-black/80 text-white text-xs py-1 px-2 rounded whitespace-nowrap"
              style={{ left: `${hoverProgress}%` }}
            >
              {formatTime((hoverProgress / 100) * (videoRef.current?.duration || 0))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
