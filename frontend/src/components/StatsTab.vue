<script setup>
import { computed, onMounted, ref } from 'vue'
import { PARKING_DATA } from '@frontend/data/parkingData'
import { useParkingLots } from '@frontend/composables/parkingLots'
import { useT } from '@frontend/composables/i18n'
import Sparkline from '@frontend/components/charts/Sparkline.vue'
import ForecastChart from '@frontend/components/charts/ForecastChart.vue'
import BarChart from '@frontend/components/charts/BarChart.vue'
import DonutChart from '@frontend/components/charts/DonutChart.vue'

const { t } = useT()
const range = ref('7d')
const forecastData = ref(null)
const { lots, loadLots } = useParkingLots()
const { HOURLY, WEEK, REVENUE, ANOMALIES } = PARKING_DATA

onMounted(() => {
  loadLots().catch(() => {})
  loadOccupancyForecast().catch(() => {})
})

async function loadOccupancyForecast() {
  const response = await fetch('/api/stats/occupancy-forecast?hours=24', {
    credentials: 'include',
  })

  if (!response.ok) return
  forecastData.value = await response.json()
}

function heatColor(v) {
  if (v < 33) return `rgba(0, 61, 165, ${0.15 + (v / 33) * 0.55})`
  if (v < 66) return `rgba(217, 119, 6, ${0.55 + ((v - 33) / 33) * 0.25})`
  return `rgba(200, 16, 46, ${0.65 + ((v - 66) / 34) * 0.3})`
}

const stats = computed(() => {
  const enabled = lots.value.filter(l => l.state === 'enabled')
  const totalSpots = enabled.reduce((sum, l) => sum + l.total, 0)
  const totalOccupied = enabled.reduce((sum, l) => sum + l.occupied, 0)
  return {
    totalSpots,
    totalOccupied,
    occupancyPct: totalSpots ? Math.round((totalOccupied / totalSpots) * 100) : 0,
    revenueToday: enabled.reduce((sum, l) => sum + l.revenue, 0),
    avgDuration: 47,
    lots: enabled.length,
  }
})

const leaderboard = computed(() => [...lots.value].filter(l => l.state === 'enabled').sort((a, b) => b.occupied - a.occupied).slice(0, 6))
const maxLb = computed(() => Math.max(1, ...leaderboard.value.map(l => l.occupied)))
const fallbackForecast = computed(() => HOURLY.map((v, i) => Math.min(100, Math.max(5, v + Math.sin(i * 0.6) * 4 + 2))))
const hours = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'))
const actualSeries = computed(() => {
  const values = forecastData.value?.actual?.map(item => Number(item.occupancy))
  return values?.length === HOURLY.length ? values : HOURLY
})
const forecastSeries = computed(() => {
  const values = forecastData.value?.forecast?.map(item => Number(item.occupancy))
  return values?.length === HOURLY.length ? values : fallbackForecast.value
})
const forecastLabels = computed(() => {
  const labels = forecastData.value?.forecast?.map(item => item.label)
  return labels?.length === HOURLY.length ? labels : hours
})
const forecastSubtitle = computed(() => {
  if (forecastData.value?.trained) return t('stats.panel.forecast.ai_sub')
  if (forecastData.value) return t('stats.panel.forecast.fallback_sub')
  return t('stats.panel.forecast.sub')
})
const revLabels = Array.from({ length: 14 }, (_, i) => `${14 - i}z`).reverse()
const days = computed(() => [0, 1, 2, 3, 4, 5, 6].map(i => t(`stats.day.${i}`)))
function countSpacesByType(enabledLots, type) {
  return enabledLots.reduce((sum, lot) => sum + Number(lot.spaceTypeCounts?.[type] || 0), 0)
}

const mixData = computed(() => [
  { label: t('stats.mix.normal'), value: countSpacesByType(lots.value.filter(l => l.state === 'enabled'), 'normal'), color: 'var(--bm-blue)' },
  { label: t('stats.mix.electric'), value: countSpacesByType(lots.value.filter(l => l.state === 'enabled'), 'electric'), color: '#16a34a' },
  { label: t('stats.mix.handicap'), value: countSpacesByType(lots.value.filter(l => l.state === 'enabled'), 'handicap'), color: 'var(--bm-red)' },
])
</script>

<template>
  <div class="stats-wrap">
    <div class="stats-head">
      <div>
        <h1>{{ t('stats.title') }}</h1>
        <div class="sub">{{ t('stats.sub') }}</div>
      </div>
      <div class="range-pills">
        <button v-for="item in ['24h', '7d', '30d', '90d']" :key="item" :class="{ active: range === item }"
          @click="range = item">{{ item }}</button>
      </div>
    </div>

    <div class="kpi-grid">
      <div class="kpi">
        <div class="kpi-label">{{ t('stats.kpi.spots') }}</div>
        <div class="kpi-value">{{ stats.totalSpots.toLocaleString('ro-RO') }}</div>
        <div class="kpi-delta up">{{ t('stats.kpi.spots.delta') }}</div>
        <div class="kpi-spark">
          <Sparkline :data="[1610, 1620, 1625, 1640, 1648, 1650, 1652]" color="var(--bm-blue)" />
        </div>
      </div>
      <div class="kpi">
        <div class="kpi-label">{{ t('stats.kpi.occupancy') }}</div>
        <div class="kpi-value">{{ stats.occupancyPct }}<span class="unit">%</span></div>
        <div class="kpi-delta up">{{ t('stats.kpi.occupancy.delta') }}</div>
        <div class="kpi-spark">
          <Sparkline :data="HOURLY.slice(-12)" color="var(--bm-red)" />
        </div>
      </div>
      <div class="kpi">
        <div class="kpi-label">{{ t('stats.kpi.duration') }}</div>
        <div class="kpi-value">{{ stats.avgDuration }}<span class="unit">{{ t('stats.kpi.min') }}</span></div>
        <div class="kpi-delta down">{{ t('stats.kpi.duration.delta') }}</div>
        <div class="kpi-spark">
          <Sparkline :data="[52, 49, 51, 48, 50, 47, 47]" color="var(--bm-blue)" />
        </div>
      </div>
      <div class="kpi">
        <div class="kpi-label">{{ t('stats.kpi.revenue') }}</div>
        <div class="kpi-value">{{ (stats.revenueToday / 1000).toFixed(1) }}<span class="unit">{{ t('stats.kpi.k_lei')
            }}</span></div>
        <div class="kpi-delta up">{{ t('stats.kpi.revenue.delta') }}</div>
        <div class="kpi-spark">
          <Sparkline :data="REVENUE.slice(-7).map(v => v / 1000)" color="var(--good)" />
        </div>
      </div>
    </div>

    <div class="charts-grid">
      <div class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">{{ t('stats.panel.forecast.title') }}</div>
            <div class="panel-sub">{{ forecastSubtitle }}</div>
          </div>
        </div>
        <ForecastChart :actual="actualSeries" :forecast="forecastSeries" :labels="forecastLabels" />
      </div>

      <div class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">{{ t('stats.panel.mix.title') }}</div>
            <div class="panel-sub">{{ stats.lots }} {{ t('stats.panel.mix.sub_count') }}</div>
          </div>
        </div>
        <DonutChart :spots-label="t('stats.spots')" :data="mixData" />
      </div>
    </div>

    <div class="heatmap-grid">
      <div class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">{{ t('stats.panel.heatmap.title') }}</div>
            <div class="panel-sub">{{ t('stats.panel.heatmap.sub') }}</div>
          </div>
        </div>
        <div class="heatmap">
          <div></div>
          <div v-for="(h, i) in hours" :key="h" class="hlabel">{{ i % 2 === 0 ? h : '' }}</div>
          <template v-for="(row, di) in WEEK" :key="di">
            <div class="hlabel">{{ days[di] }}</div>
            <div v-for="(v, hi) in row" :key="`${di}-${hi}`" class="hcell" :style="{ background: heatColor(v) }"
              :data-tip="`${days[di]} ${hours[hi]}:00 · ${v}%`"></div>
          </template>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">{{ t('stats.panel.top.title') }}</div>
            <div class="panel-sub">{{ t('stats.panel.top.sub') }}</div>
          </div>
        </div>
        <div class="leaderboard">
          <div v-for="(lot, i) in leaderboard" :key="lot.id" class="lb-row">
            <div class="rank">{{ i + 1 }}</div>
            <div>
              <div class="lname">{{ lot.name }}</div>
              <div class="lsub">{{ lot.id }} · {{ lot.owner }}</div>
            </div>
            <div class="lbar">
              <div class="f" :style="{ width: `${(lot.occupied / maxLb) * 100}%` }"></div>
            </div>
            <div class="lval">{{ lot.occupied }}/{{ lot.total }}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="heatmap-grid">
      <div class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">{{ t('stats.panel.revenue.title') }}</div>
            <div class="panel-sub">{{ t('stats.panel.revenue.total') }} {{(REVENUE.reduce((s, v) => s + v, 0) /
              1000).toFixed(1) }}k lei</div>
          </div>
        </div>
        <BarChart :data="REVENUE" :labels="revLabels" color="var(--bm-red)" />
      </div>

      <div class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">{{ t('stats.panel.anomalies.title') }}</div>
            <div class="panel-sub">{{ ANOMALIES.length }} {{ t('stats.panel.anomalies.active') }}</div>
          </div><button class="btn-ghost">{{ t('stats.panel.anomalies.viewall') }}</button>
        </div>
        <div class="anomalies-list">
          <div v-for="item in ANOMALIES" :key="item.id" class="anomaly">
            <div class="sev-dot"
              :style="{ background: { high: 'var(--bad)', medium: 'var(--warn)', low: 'var(--text-faint)' }[item.severity] }">
            </div>
            <div>
              <div class="a-title">{{ item.message }}</div>
              <div class="a-sub">{{ t('stats.anomaly.lot') }} {{ item.lot }}</div>
            </div>
            <div class="a-time">{{ item.time }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
