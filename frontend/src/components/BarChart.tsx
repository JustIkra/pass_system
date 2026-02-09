import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart as BarChartComponent } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  BarChartComponent,
  GridComponent,
  TooltipComponent,
  CanvasRenderer,
]);

interface BarChartDataPoint {
  name: string;
  value: number;
}

interface BarChartProps {
  data: BarChartDataPoint[];
  title?: string;
  yAxisLabel?: string;
  color?: string;
}

function formatNumber(n: number): string {
  return Math.round(n)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

export default function BarChart({
  data,
  title,
  yAxisLabel,
  color = '#2563EB',
}: BarChartProps) {
  const sorted = [...data].sort((a, b) => b.value - a.value);

  const option: echarts.EChartsOption = {
    title: title
      ? {
          text: title,
          left: 'center',
          textStyle: { fontSize: 14, fontWeight: 600, color: '#0F172A' },
        }
      : undefined,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: unknown) => {
        const p = params as Array<{ name: string; value: number }>;
        const first = p[0];
        if (!first) return '';
        return `<strong>${first.name}</strong><br/>${yAxisLabel ?? 'Значение'}: ${formatNumber(first.value)}`;
      },
    },
    grid: {
      top: title ? 50 : 20,
      bottom: 10,
      left: 200,
      right: 30,
      containLabel: false,
    },
    xAxis: {
      type: 'value',
      axisLabel: {
        fontSize: 11,
        color: '#64748B',
        formatter: (val: number) => formatNumber(val),
      },
      splitLine: { lineStyle: { color: '#E2E8F0' } },
    },
    yAxis: {
      type: 'category',
      data: sorted.map((d) => d.name),
      inverse: true,
      axisLabel: {
        fontSize: 12,
        color: '#0F172A',
        width: 180,
        overflow: 'truncate',
      },
    },
    series: [
      {
        type: 'bar',
        data: sorted.map((d) => d.value),
        barWidth: '60%',
        itemStyle: {
          color,
          borderRadius: [0, 4, 4, 0],
        },
        label: {
          show: true,
          position: 'right',
          fontSize: 11,
          color: '#0F172A',
          formatter: (params: unknown) => {
            const p = params as { value: number };
            return formatNumber(p.value);
          },
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
        style={{ height: Math.max(200, sorted.length * 40 + 60) }}
        notMerge
      />
    </div>
  );
}
