/**
 * Open turn-by-turn directions to a destination in the device's native maps app.
 * iOS / macOS -> Apple Maps. Everything else -> Google Maps universal link
 * (opens the Google Maps app on Android, falls back to the browser on desktop).
 * Origin is omitted so the maps app routes from the device's current location.
 */
export function openDirections(lat, lng) {
  const isApple = /iPad|iPhone|iPod|Macintosh/.test(navigator.userAgent || '')
  const url = isApple
    ? `https://maps.apple.com/?daddr=${lat},${lng}`
    : `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`
  window.open(url, '_blank', 'noopener')
}