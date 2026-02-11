/** Prediction direction colors: increase = green, decrease = red. Use for consistent layout across cards and tables. */
export const PREDICTION_COLORS = {
  up: '#22c55e',
  down: '#ef4444',
  neutral: '#e5e7eb',
  neutralMuted: '#666666',
} as const;

export function getPredictionStyle(predictionText: string): { color: string; bg?: string; border?: string } {
  const isUp = predictionText.includes('↑');
  const isDown = predictionText.includes('↓');
  if (isUp) {
    return { color: PREDICTION_COLORS.up, bg: 'rgba(34, 197, 94, 0.15)', border: 'rgba(34, 197, 94, 0.4)' };
  }
  if (isDown) {
    return { color: PREDICTION_COLORS.down, bg: 'rgba(239, 68, 68, 0.15)', border: 'rgba(239, 68, 68, 0.4)' };
  }
  return { color: PREDICTION_COLORS.neutral, bg: 'rgba(229, 231, 235, 0.15)', border: 'rgba(229, 231, 235, 0.4)' };
}

/** Direction bias (UP/DOWN/NEUTRAL/MIXED) to color: increase = green, decrease = red. */
export function getDirectionColor(directionBias: string | null | undefined): string {
  const d = (directionBias || '').toUpperCase();
  if (d === 'UP') return PREDICTION_COLORS.up;
  if (d === 'DOWN') return PREDICTION_COLORS.down;
  return PREDICTION_COLORS.neutralMuted;
}
