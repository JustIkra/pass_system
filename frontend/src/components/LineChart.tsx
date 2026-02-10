import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { LineChart as LineChartComponent } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  LineChartComponent,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  CanvasRenderer,
]);

interface LineChartDataPoint {
  date: string;
  value: number;
  lower: number;
  upper: number;
}

interface LineChartProps {
  data: LineChartDataPoint[];
  title?: string;
  yAxisLabel?: string;
}

function formatNumber(n: number): string {
  return Math.round(n)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

export default function LineChart({ data, title, yAxisLabel }: LineChartProps) {
  const dates = data.map((d) => d.date);
  const values = data.map((d) => d.value);
  const lowerValues = data.map((d) => d.lower);
  const upperValues = data.map((d) => d.upper);

  const option: echarts.EChartsCoreOption = {
    title: title
      ? {
          text: title,
          left: 'center',
          textStyle: { fontSize: 14, fontWeight: 600, color: '#0F172A' },
        }
      : undefined,
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const p = params as Array<{ axisValue: string; value: number; seriesName: string }>;
        const first = p[0];
        if (!first) return '';
        const idx = dates.indexOf(first.axisValue);
        const lower = lowerValues[idx];
        const upper = upperValues[idx];
        let html = `<strong>${first.axisValue}</strong><br/>`;
        html += `Прогноз: ${formatNumber(first.value)}<br/>`;
        if (lower !== undefined && upper !== undefined) {
          html += `Интервал: ${formatNumber(lower)} - ${formatNumber(upper)}`;
        }
        return html;
      },
    },
    grid: {
      top: title ? 50 : 30,
      bottom: 60,
      left: 60,
      right: 20,
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: {
        fontSize: 11,
        color: '#64748B',
        rotate: 45,
      },
    },
    yAxis: {
      type: 'value',
      name: yAxisLabel,
      nameTextStyle: { fontSize: 11, color: '#64748B' },
      axisLabel: {
        fontSize: 11,
        color: '#64748B',
        formatter: (val: number) => formatNumber(val),
      },
      splitLine: { lineStyle: { color: '#E2E8F0' } },
    },
    dataZoom: [
      {
        type: 'inside',
        start: 0,
        end: 100,
      },
      {
        type: 'slider',
        start: 0,
        end: 100,
        height: 20,
        bottom: 5,
      },
    ],
    series: [
      {
        name: 'Нижняя граница',
        type: 'line',
        data: lowerValues,
        lineStyle: { opacity: 0, width: 0 },
        stack: 'confidence',
        symbol: 'none',
        silent: true,
      },
      {
        name: 'Доверительный интервал',
        type: 'line',
        data: upperValues.map((u, i) => {
          const l = lowerValues[i] ?? 0;
          return u - l;
        }),
        lineStyle: { opacity: 0, width: 0 },
        areaStyle: {
          color: 'rgba(37, 99, 235, 0.15)',
        },
        stack: 'confidence',
        symbol: 'none',
        silent: true,
      },
      {
        name: 'Прогноз',
        type: 'line',
        data: values,
        lineStyle: { color: '#2563EB', width: 2 },
        itemStyle: { color: '#2563EB' },
        symbol: 'circle',
        symbolSize: 4,
        emphasis: {
          itemStyle: { borderWidth: 2 },
        },
      },
    ],
  };

  if (data.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-[#E2E8F0] p-8 text-center text-[#64748B]">
        Недостаточно данных для построения графика.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-[#E2E8F0] p-4">
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        style={{ height: 340 }}
        notMerge
      />
    </div>
  );
}
