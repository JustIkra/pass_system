import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { HeatmapChart as HeatmapChartComponent } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  HeatmapChartComponent,
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

interface HeatmapDataPoint {
  dayOfWeek: number;
  hour: number;
  value: number;
}

interface HeatmapChartProps {
  data: HeatmapDataPoint[];
  title?: string;
}

const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const HOURS = Array.from({ length: 12 }, (_, i) => `${(8 + i).toString().padStart(2, '0')}:00`);

export default function HeatmapChart({ data, title }: HeatmapChartProps) {
  const maxValue = data.length > 0 ? Math.max(...data.map((d) => d.value)) : 100;

  const formattedData = data.map((d) => [d.hour - 8, d.dayOfWeek, d.value]);

  const option: echarts.EChartsOption = {
    title: title
      ? {
          text: title,
          left: 'center',
          textStyle: { fontSize: 14, fontWeight: 600, color: '#0F172A' },
        }
      : undefined,
    tooltip: {
      position: 'top',
      formatter: (params: unknown) => {
        const p = params as { value: [number, number, number] };
        const dayIdx = p.value[1];
        const hourIdx = p.value[0];
        const val = p.value[2];
        const day = DAYS[dayIdx] ?? '';
        const hour = HOURS[hourIdx] ?? '';
        return `<strong>${day} ${hour}</strong><br/>Обращений: ${Math.round(val)}`;
      },
    },
    grid: {
      top: title ? 50 : 20,
      bottom: 40,
      left: 50,
      right: 40,
    },
    xAxis: {
      type: 'category',
      data: HOURS,
      splitArea: { show: true },
      axisLabel: { fontSize: 11, color: '#64748B' },
    },
    yAxis: {
      type: 'category',
      data: DAYS,
      splitArea: { show: true },
      axisLabel: { fontSize: 11, color: '#64748B' },
    },
    visualMap: {
      min: 0,
      max: maxValue || 1,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemWidth: 14,
      itemHeight: 120,
      textStyle: { fontSize: 11, color: '#64748B' },
      inRange: {
        color: ['#F3F4F6', '#22C55E', '#F97316', '#EF4444'],
      },
    },
    series: [
      {
        name: 'Загрузка',
        type: 'heatmap',
        data: formattedData,
        label: {
          show: true,
          fontSize: 10,
          color: '#0F172A',
          formatter: (params: unknown) => {
            const p = params as { value: [number, number, number] };
            return String(Math.round(p.value[2]));
          },
        },
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowColor: 'rgba(0,0,0,0.3)',
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
        style={{ height: 280 }}
        notMerge
      />
    </div>
  );
}
