import ReactECharts from 'echarts-for-react';

interface Props {
  data: Record<string, unknown>[];
  xField: string;
  yField: string;
  chartType: 'bar' | 'line';
}

export default function ResultChart({ data, xField, yField, chartType }: Props) {
  const xData = data.map((d) => String(d[xField] ?? ''));
  const yData = data.map((d) => Number(d[yField] ?? 0));

  const option = {
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: xData },
    yAxis: { type: 'value' },
    series: [{
      data: yData,
      type: chartType,
      smooth: chartType === 'line',
    }],
  };

  return <ReactECharts option={option} style={{ height: 400 }} />;
}
