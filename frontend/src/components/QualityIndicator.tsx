import { useState } from 'react';
import type { QualityMetrics } from '../types';

interface QualityIndicatorProps {
  metrics?: QualityMetrics;
  variant?: 'badge' | 'inline' | 'detailed';
}

function getQualityLevel(wMAPE: number): 'high' | 'medium' | 'low' | 'unavailable' {
  if (wMAPE < 15) return 'high';
  if (wMAPE < 25) return 'medium';
  if (wMAPE < 100) return 'low';
  return 'unavailable';
}

function getQualityLabel(level: string): string {
  const labels: Record<string, string> = {
    high: 'отличная',
    medium: 'приемлемая',
    low: 'ограниченная',
    unavailable: 'недоступна'
  };
  return labels[level] || '';
}

export function QualityIndicator({ metrics, variant = 'badge' }: QualityIndicatorProps) {
  const [showTooltip, setShowTooltip] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  if (!metrics) {
    return (
      <span className="quality-badge quality-unavailable">
        Качество недоступно
      </span>
    );
  }

  const quality = getQualityLevel(metrics.wMAPE);
  const qualityLabel = getQualityLabel(quality);

  // Badge variant (компактный)
  if (variant === 'badge') {
    return (
      <div className="relative inline-block">
        <span
          className={`quality-badge quality-${quality}`}
          onMouseEnter={() => setShowTooltip(true)}
          onMouseLeave={() => setShowTooltip(false)}
        >
          wMAPE {metrics.wMAPE.toFixed(1)}%
        </span>

        {showTooltip && (
          <div className="absolute z-50 w-64 p-3 mt-2 text-sm bg-white border border-gray-200 rounded-lg shadow-lg -left-24">
            <div className="font-semibold mb-2">Точность прогноза</div>
            <div className="space-y-1 text-gray-600">
              <div>wMAPE: {metrics.wMAPE.toFixed(1)}% ({qualityLabel})</div>
              <div>Уверенность: {metrics.confidence.toFixed(0)}%</div>
              <div>Данных: {metrics.training_days} дней</div>
              {metrics.last_updated && (
                <div className="text-xs text-gray-500 mt-2">
                  Обновлено: {new Date(metrics.last_updated).toLocaleDateString('ru-RU')}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  // Inline variant (с текстом)
  if (variant === 'inline') {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-600">
        <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        Точность прогноза: wMAPE {metrics.wMAPE.toFixed(1)}%
        <span className={`quality-${quality}-text font-medium`}>
          ({qualityLabel})
        </span>
      </div>
    );
  }

  // Detailed variant (с рекомендациями)
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className={`quality-badge quality-${quality}`}>
          wMAPE {metrics.wMAPE.toFixed(1)}% — {qualityLabel} точность
        </span>
        <button
          onClick={() => setShowDetails(!showDetails)}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          {showDetails ? 'Скрыть' : 'Подробнее'} ▼
        </button>
      </div>

      {metrics.recommendations && quality === 'low' && (
        <div className="quality-info-panel">
          <div className="flex items-start gap-2">
            <svg className="w-5 h-5 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
            </svg>
            <div>
              <div className="font-semibold mb-1">Точность прогноза ограничена</div>
              <div className="text-sm">
                Причина: недостаточно исторических данных ({metrics.training_days} дней вместо рекомендуемых 360)
              </div>
              <div className="mt-2">
                <div className="font-medium text-sm mb-1">Рекомендации:</div>
                <ul>
                  {metrics.recommendations.map((rec, idx) => (
                    <li key={idx}>{rec}</li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {showDetails && (
        <div className="p-4 bg-gray-50 rounded-lg text-sm space-y-2">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-gray-500">wMAPE (взвеш. откл.)</div>
              <div className="font-semibold">{metrics.wMAPE.toFixed(1)}%</div>
              <div className="text-xs text-gray-500">целевой &lt; 20%</div>
            </div>
            <div>
              <div className="text-gray-500">Уверенность</div>
              <div className="font-semibold">{metrics.confidence.toFixed(0)}%</div>
              <div className="text-xs text-gray-500">на основе данных</div>
            </div>
            <div>
              <div className="text-gray-500">Обучающих данных</div>
              <div className="font-semibold">{metrics.training_days} дней</div>
              <div className="text-xs text-gray-500">мин. 360 дней</div>
            </div>
            <div>
              <div className="text-gray-500">Последнее обновление</div>
              <div className="font-semibold">
                {new Date(metrics.last_updated).toLocaleDateString('ru-RU')}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
