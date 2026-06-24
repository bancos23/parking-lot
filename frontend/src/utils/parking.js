export function colorForOccupancy(occupied, total) {
  const ratio = total > 0 ? occupied / total : 0

  if (ratio >= 0.85) return '#dc2626'
  if (ratio >= 0.5) return '#d97706'

  return '#16a34a'
}

export function spaceTypeGlyph(type) {
  if (type === 'electric') return '⚡'
  if (type === 'handicap') return '♿'

  return 'P'
}
