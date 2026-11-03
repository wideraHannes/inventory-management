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
          <span class="budget-value">{{ currencySymbol }}{{ budget.toLocaleString() }}</span>
        </div>
        <input
          id="budget-slider"
          v-model.number="budget"
          type="range"
          min="0"
          :max="maxBudget"
          :step="BUDGET_STEP"
          class="budget-slider"
        />
        <div class="budget-scale">
          <span>{{ currencySymbol }}0</span>
          <span>{{ currencySymbol }}{{ maxBudget.toLocaleString() }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ budget.toLocaleString() }}</div>
        </div>
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.plannedCost') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ plannedCost.toLocaleString() }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ remainingBudget.toLocaleString() }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.maxLeadTime') }}</div>
          <div class="stat-value">{{ t('restocking.days', { count: maxLeadTime }) }}</div>
        </div>
      </div>

      <div v-if="orderSuccess" class="success-message">
        {{ t('restocking.orderPlaced', { orderNumber: orderSuccess.order_number }) }}
        <router-link to="/orders">{{ t('restocking.viewInOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="error">{{ submitError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }}</h3>
          <button
            class="place-order-btn"
            :disabled="!canPlaceOrder"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>
        <div v-if="recommendations.length === 0" class="empty-state">
          {{ t('restocking.noRecommendations') }}
        </div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th class="col-include">{{ t('restocking.table.include') }}</th>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.need') }}</th>
                <th>{{ t('restocking.table.recommendedQty') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.subtotal') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in recommendations"
                :key="item.item_sku"
                :class="{ excluded: item.excluded }"
              >
                <td class="col-include">
                  <input
                    type="checkbox"
                    :checked="!item.excluded"
                    :aria-label="item.item_sku"
                    @change="toggleItem(item.item_sku)"
                  />
                </td>
                <td><strong>{{ item.item_sku }}</strong></td>
                <td>{{ translateProductName(item.item_name) }}</td>
                <td>
                  <span :class="['badge', item.trend]">
                    {{ t(`trends.${item.trend}`) }}
                  </span>
                </td>
                <td>{{ item.need }}</td>
                <td><strong>{{ item.quantity }}</strong></td>
                <td>{{ currencySymbol }}{{ item.unit_cost.toLocaleString() }}</td>
                <td>{{ currencySymbol }}{{ item.subtotal.toLocaleString() }}</td>
                <td>{{ item.lead_time_days }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

const BUDGET_STEP = 500

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    const currencySymbol = computed(() => {
      return currentCurrency.value === 'JPY' ? '¥' : '$'
    })

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const budget = ref(0)
    // SKUs the user unchecked; the Set is replaced (not mutated) on toggle so Vue tracks the change
    const excludedSkus = ref(new Set())
    const submitting = ref(false)
    const submitError = ref(null)
    const orderSuccess = ref(null)

    // Units still missing to cover forecasted demand (never negative)
    const getNeed = (f) => Math.max(f.forecasted_demand - f.current_demand, 0)

    // Items with a positive need, before any budget allocation
    const needItems = computed(() => {
      return forecasts.value.filter(f => getNeed(f) > 0)
    })

    // Slider max: cost of covering every positive need, rounded up to the slider step
    const maxBudget = computed(() => {
      const total = needItems.value.reduce((sum, f) => sum + getNeed(f) * f.unit_cost, 0)
      return Math.ceil(total / BUDGET_STEP) * BUDGET_STEP
    })

    /*
     * Recommendation logic:
     * 1. Only items with need = max(forecasted - current demand, 0) > 0 are considered.
     * 2. Priority: 'increasing' trend first, then by descending need value (need * unit_cost).
     * 3. Greedy allocation over the priority list: buy the full need if it fits the
     *    remaining budget, otherwise buy floor(remaining / unit_cost) units (skipped if 0)
     *    and keep going, since cheaper items further down may still fit.
     * 4. Items the user unchecked are excluded from allocation (quantity 0) so their
     *    budget flows to the next items, but they stay in the table to be re-included.
     */
    const recommendations = computed(() => {
      const sorted = needItems.value
        .map(f => ({ ...f, need: getNeed(f) }))
        .sort((a, b) => {
          const aInc = a.trend === 'increasing' ? 1 : 0
          const bInc = b.trend === 'increasing' ? 1 : 0
          if (aInc !== bInc) return bInc - aInc
          return b.need * b.unit_cost - a.need * a.unit_cost
        })

      let remaining = budget.value
      return sorted.map(item => {
        const excluded = excludedSkus.value.has(item.item_sku)
        let quantity = 0
        if (!excluded && item.unit_cost > 0) {
          quantity = Math.min(item.need, Math.floor(remaining / item.unit_cost))
        }
        const subtotal = quantity * item.unit_cost
        remaining -= subtotal
        return { ...item, excluded, quantity, subtotal }
      })
    })

    const orderItems = computed(() => recommendations.value.filter(r => r.quantity > 0))

    const plannedCost = computed(() => {
      return orderItems.value.reduce((sum, r) => sum + r.subtotal, 0)
    })

    const remainingBudget = computed(() => budget.value - plannedCost.value)

    const maxLeadTime = computed(() => {
      return orderItems.value.reduce((max, r) => Math.max(max, r.lead_time_days), 0)
    })

    // Block re-submitting the identical order: the button re-enables once the plan changes
    const justPlaced = ref(false)
    watch([budget, excludedSkus], () => { justPlaced.value = false })

    const canPlaceOrder = computed(() => orderItems.value.length > 0 && !submitting.value && !justPlaced.value)

    const toggleItem = (sku) => {
      const next = new Set(excludedSkus.value)
      if (next.has(sku)) {
        next.delete(sku)
      } else {
        next.add(sku)
      }
      excludedSkus.value = next
    }

    const loadForecasts = async () => {
      try {
        loading.value = true
        error.value = null
        forecasts.value = await api.getDemandForecasts()
        // Default budget: ~50% of max, snapped to the slider step
        budget.value = Math.round((maxBudget.value / 2) / BUDGET_STEP) * BUDGET_STEP
      } catch (err) {
        error.value = 'Failed to load demand forecasts: ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (!canPlaceOrder.value) return
      submitting.value = true
      submitError.value = null
      orderSuccess.value = null
      try {
        orderSuccess.value = await api.createRestockingOrder({
          budget: budget.value,
          items: orderItems.value.map(r => ({
            sku: r.item_sku,
            name: r.item_name,
            quantity: r.quantity,
            unit_cost: r.unit_cost,
            lead_time_days: r.lead_time_days
          }))
        })
        justPlaced.value = true
      } catch (err) {
        // FastAPI returns a string detail for 400s but an array of objects for 422 validation errors
        const detail = err.response?.data?.detail
        submitError.value = typeof detail === 'string' ? detail : t('restocking.orderFailed') + ': ' + err.message
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadForecasts)

    return {
      t,
      BUDGET_STEP,
      currencySymbol,
      translateProductName,
      loading,
      error,
      budget,
      maxBudget,
      recommendations,
      plannedCost,
      remainingBudget,
      maxLeadTime,
      canPlaceOrder,
      submitting,
      submitError,
      orderSuccess,
      toggleItem,
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

.budget-slider {
  width: 100%;
  accent-color: #3b82f6;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  font-size: 0.813rem;
  color: #64748b;
  margin-top: 0.25rem;
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

.col-include {
  width: 70px;
  text-align: center;
}

tr.excluded td {
  color: #94a3b8;
}

tr.excluded .badge {
  opacity: 0.5;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}

.success-message {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
  font-size: 0.938rem;
}

.success-message a {
  margin-left: 0.5rem;
  color: #166534;
  font-weight: 600;
  text-decoration: underline;
}
</style>
