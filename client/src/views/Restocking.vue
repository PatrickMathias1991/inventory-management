<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="budget-row">
          <label class="budget-label" for="budget-slider">{{ t('restocking.budget') }}</label>
          <span class="budget-value">{{ money(budget) }}</span>
        </div>
        <input
          id="budget-slider"
          v-model.number="budget"
          type="range"
          class="budget-slider"
          min="0"
          :max="maxBudget"
          :step="STEP"
          :style="{ '--fill': fillPercent + '%' }"
        />
        <p class="budget-hint">{{ t('restocking.budgetHint') }}</p>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.budgetSpent') }}</div>
          <div class="stat-value">{{ money(totalCost) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.budgetRemaining') }}</div>
          <div class="stat-value">{{ money(budget - totalCost) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.longestLeadTime') }}</div>
          <div class="stat-value">{{ t('restocking.days', { count: longestLeadTime }) }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }} ({{ recommendation.length }})</h3>
          <button
            type="button"
            class="place-order-btn"
            :disabled="recommendation.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="submitError" class="error">
          {{ t('restocking.orderFailed') }}: {{ submitError }}
        </div>
        <div v-if="placedOrder" class="success-message">
          <strong>{{ t('restocking.orderPlaced') }}.</strong>
          {{ t('restocking.orderPlacedDetail', { id: placedOrder.id, date: formatDate(placedOrder.expected_delivery_date) }) }}
          <router-link to="/orders">{{ t('restocking.viewOrders') }}</router-link>
        </div>

        <div v-if="recommendation.length === 0" class="loading">{{ t('restocking.empty') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.quantity') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineTotal') }}</th>
                <th>{{ t('restocking.table.supplier') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="line in recommendation" :key="line.item_sku">
                <td><strong>{{ line.item_sku }}</strong></td>
                <td>{{ line.item_name }}</td>
                <td>
                  <span :class="['badge', line.trend]">{{ t(`trends.${line.trend}`) }}</span>
                </td>
                <td>{{ line.quantity }}</td>
                <td>{{ money(line.unit_cost, 2) }}</td>
                <td><strong>{{ money(line.lineTotal, 2) }}</strong></td>
                <td>{{ line.supplier_name }}</td>
                <td>{{ line.lead_time_days }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

const STEP = 100
const TREND_RANK = { increasing: 0, stable: 1, decreasing: 2 }

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, currentLocale } = useI18n()
    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const budget = ref(0)
    const submitting = ref(false)
    const submitError = ref(null)
    const placedOrder = ref(null)

    // Budget is kept in USD; conversion happens only in the display helpers.
    const money = (amount, decimals = 0) => decimals > 0
      ? formatCurrencyWithDecimals(amount, currentCurrency.value, decimals)
      : formatCurrency(amount, currentCurrency.value)

    const gapItems = computed(() => {
      return forecasts.value
        .map(f => ({ ...f, gap: f.forecasted_demand - f.current_demand }))
        .filter(f => f.gap > 0 && f.unit_cost > 0)
        .sort((a, b) => {
          const rankA = TREND_RANK[a.trend] ?? 3
          const rankB = TREND_RANK[b.trend] ?? 3
          return rankA - rankB || b.gap - a.gap
        })
    })

    const maxBudget = computed(() => {
      const full = gapItems.value.reduce((sum, f) => sum + f.gap * f.unit_cost, 0)
      return Math.ceil(full / STEP) * STEP
    })

    const fillPercent = computed(() => maxBudget.value > 0 ? (budget.value / maxBudget.value) * 100 : 0)

    const recommendation = computed(() => {
      let remaining = budget.value
      const lines = []
      for (const item of gapItems.value) {
        const quantity = Math.min(item.gap, Math.floor(remaining / item.unit_cost))
        if (quantity >= 1) {
          const lineTotal = quantity * item.unit_cost
          lines.push({ ...item, quantity, lineTotal })
          remaining -= lineTotal
        }
      }
      return lines
    })

    const totalCost = computed(() => recommendation.value.reduce((sum, l) => sum + l.lineTotal, 0))

    const longestLeadTime = computed(() =>
      recommendation.value.reduce((max, l) => Math.max(max, l.lead_time_days || 0), 0)
    )

    const formatDate = (dateString) => {
      const date = new Date(dateString)
      if (isNaN(date.getTime())) return dateString
      return date.toLocaleDateString(currentLocale.value === 'ja' ? 'ja-JP' : 'en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      })
    }

    const loadForecasts = async () => {
      try {
        loading.value = true
        forecasts.value = await api.getDemandForecasts()
        budget.value = Math.round(maxBudget.value / 2 / STEP) * STEP
      } catch (err) {
        error.value = t('restocking.loadFailed') + ': ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (recommendation.value.length === 0 || submitting.value) return
      submitting.value = true
      submitError.value = null
      placedOrder.value = null
      try {
        placedOrder.value = await api.createRestockingOrder({
          items: recommendation.value.map(l => ({ item_sku: l.item_sku, quantity: l.quantity }))
        })
      } catch (err) {
        submitError.value = err.response?.data?.detail || err.message
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadForecasts)

    return {
      t,
      STEP,
      loading,
      error,
      budget,
      maxBudget,
      fillPercent,
      recommendation,
      totalCost,
      longestLeadTime,
      submitting,
      submitError,
      placedOrder,
      money,
      formatDate,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.25rem;
  margin-bottom: 1.5rem;
}

.budget-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 0.75rem;
}

.budget-label {
  color: #64748b;
  font-size: 0.875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.budget-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-hint {
  margin-top: 0.75rem;
  color: #64748b;
  font-size: 0.813rem;
}

.budget-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 6px;
  border-radius: 3px;
  outline: none;
  cursor: pointer;
  background: linear-gradient(to right, #0f172a 0%, #0f172a var(--fill, 0%), #e2e8f0 var(--fill, 0%), #e2e8f0 100%);
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #0f172a;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.4);
}

.budget-slider::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #0f172a;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.4);
}

.budget-slider::-moz-range-track {
  height: 6px;
  border-radius: 3px;
  background: #e2e8f0;
}

.budget-slider::-moz-range-progress {
  height: 6px;
  border-radius: 3px;
  background: #0f172a;
}

.budget-slider:focus-visible {
  outline: 2px solid #3b82f6;
  outline-offset: 4px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.place-order-btn {
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 0.5rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.place-order-btn:hover:not(:disabled) {
  background: #1e293b;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.success-message {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
  padding: 1rem;
  border-radius: 8px;
  margin: 1rem 0;
  font-size: 0.938rem;
}

.success-message a {
  margin-left: 0.5rem;
  color: #166534;
  font-weight: 600;
  text-decoration: underline;
}
</style>
