import Image from 'next/image'

// Optimized image component with lazy loading and blur placeholder
export default function OptimizedImage({ src, alt, width, height, priority = false, className = "" }) {
  return (
    <Image
      src={src}
      alt={alt}
      width={width}
      height={height}
      priority={priority}
      className={className}
      placeholder="blur"
      blurDataURL="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
      quality={85}
      loading={priority ? 'eager' : 'lazy'}
    />
  )
}