<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen" class="modal-overlay" @click="close">
        <div class="modal-container" @click.stop>
          <div class="modal-header">
            <h3 class="modal-title">
              {{ mode === 'view' ? t('purchaseOrder.viewTitle') : t('purchaseOrder.createTitle') }}
            </h3>
            <button class="close-button" @click="close">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M15 5L5 15M5 5L15 15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
          </div>

          <div class="modal-body">
            <div v-if="backlogItem" class="item-context">
              <div class="context-name">{{ backlogItem.item_name }}</div>
              <div class="context-meta">
                <span>{{ t('purchaseOrder.sku') }}: {{ backlogItem.item_sku }}</span>
                <span>{{ t('purchaseOrder.orderId') }}: {{ backlogItem.order_id }}</span>
                <span>{{ t('purchaseOrder.shortage') }}: {{ shortage }}</span>
              </div>
            </div>

            <form v-if="mode !== 'view'" id="po-form" class="po-form" novalidate @submit.prevent="submit">
              <div class="form-group">
                <label for="po-supplier">{{ t('purchaseOrder.supplierName') }}</label>
                <input id="po-supplier" v-model="form.supplier_name" type="text" class="po-input" />
              </div>

              <div class="form-row">
                <div class="form-group">
                  <label for="po-quantity">{{ t('purchaseOrder.quantity') }}</label>
                  <input id="po-quantity" v-model="form.quantity" type="number" min="1" step="1" class="po-input" />
                </div>
                <div class="form-group">
                  <label for="po-unit-cost">{{ t('purchaseOrder.unitCost') }}</label>
                  <input id="po-unit-cost" v-model="form.unit_cost" type="number" min="0" step="0.01" class="po-input" />
                </div>
              </div>

              <div class="form-group">
                <label for="po-date">{{ t('purchaseOrder.expectedDelivery') }}</label>
                <input id="po-date" v-model="form.expected_delivery_date" type="date" class="po-input" />
              </div>

              <div class="form-group">
                <label for="po-notes">{{ t('purchaseOrder.notes') }}</label>
                <textarea id="po-notes" v-model="form.notes" rows="3" class="po-input"></textarea>
              </div>

              <div class="total-row">
                <span>{{ t('purchaseOrder.total') }}</span>
                <strong>{{ formattedTotal }}</strong>
              </div>

              <div v-if="errorMessage" class="error-message" role="alert">{{ errorMessage }}</div>
            </form>

            <template v-else>
              <div v-if="loading" class="state-message">{{ t('purchaseOrder.loading') }}</div>
              <div v-else-if="errorMessage" class="error-message" role="alert">{{ errorMessage }}</div>
              <dl v-else-if="po" class="po-details">
                <div class="detail-row">
                  <dt>{{ t('purchaseOrder.poId') }}</dt>
                  <dd>{{ po.id }}</dd>
                </div>
                <div class="detail-row">
                  <dt>{{ t('purchaseOrder.status') }}</dt>
                  <dd><span class="status-badge">{{ po.status }}</span></dd>
                </div>
                <div class="detail-row">
                  <dt>{{ t('purchaseOrder.supplierName') }}</dt>
                  <dd>{{ po.supplier_name }}</dd>
                </div>
                <div class="detail-row">
                  <dt>{{ t('purchaseOrder.quantity') }}</dt>
                  <dd>{{ po.quantity }}</dd>
                </div>
                <div class="detail-row">
                  <dt>{{ t('purchaseOrder.unitCost') }}</dt>
                  <dd>{{ money(po.unit_cost) }}</dd>
                </div>
                <div class="detail-row">
                  <dt>{{ t('purchaseOrder.total') }}</dt>
                  <dd>{{ money(po.quantity * po.unit_cost) }}</dd>
                </div>
                <div class="detail-row">
                  <dt>{{ t('purchaseOrder.createdDate') }}</dt>
                  <dd>{{ po.created_date }}</dd>
                </div>
                <div class="detail-row">
                  <dt>{{ t('purchaseOrder.expectedDelivery') }}</dt>
                  <dd>{{ po.expected_delivery_date }}</dd>
                </div>
                <div class="detail-row">
                  <dt>{{ t('purchaseOrder.notesLabel') }}</dt>
                  <dd>{{ po.notes || t('purchaseOrder.noNotes') }}</dd>
                </div>
              </dl>
            </template>
          </div>

          <div class="modal-footer">
            <button class="btn-secondary" @click="close">{{ t('profileDetails.close') }}</button>
            <button
              v-if="mode !== 'view'"
              type="submit"
              form="po-form"
              class="btn-primary"
              :disabled="submitting"
            >
              {{ submitting ? t('purchaseOrder.submitting') : t('purchaseOrder.submit') }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script>
import { ref, reactive, computed, watch } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrencyWithDecimals } from '../utils/currency'

const emptyForm = () => ({
  supplier_name: '',
  quantity: 1,
  unit_cost: '',
  expected_delivery_date: '',
  notes: ''
})

export default {
  name: 'PurchaseOrderModal',
  props: {
    isOpen: { type: Boolean, required: true },
    backlogItem: { type: Object, default: null },
    mode: { type: String, default: 'create' }
  },
  emits: ['close', 'po-created'],
  setup(props, { emit }) {
    const { t, currentCurrency } = useI18n()

    const form = reactive(emptyForm())
    const po = ref(null)
    const loading = ref(false)
    const submitting = ref(false)
    const errorMessage = ref('')

    const shortage = computed(() => {
      if (!props.backlogItem) return 0
      return Math.max(props.backlogItem.quantity_needed - props.backlogItem.quantity_available, 1)
    })

    // Costs are stored in USD; formatCurrencyWithDecimals converts for JPY.
    const money = (amount) => formatCurrencyWithDecimals(amount, currentCurrency.value, 2)

    const formTotal = computed(() => {
      const q = Number(form.quantity)
      const c = Number(form.unit_cost)
      return q > 0 && c > 0 ? q * c : 0
    })
    const formattedTotal = computed(() => money(formTotal.value))

    const validate = () => {
      if (!form.supplier_name.trim()) return t('purchaseOrder.errors.supplierRequired')
      const q = Number(form.quantity)
      if (form.quantity === '' || !Number.isInteger(q) || q < 1) return t('purchaseOrder.errors.quantityInvalid')
      const c = Number(form.unit_cost)
      if (form.unit_cost === '' || !Number.isFinite(c) || c <= 0) return t('purchaseOrder.errors.unitCostInvalid')
      if (!form.expected_delivery_date) return t('purchaseOrder.errors.dateRequired')
      return ''
    }

    const submit = async () => {
      if (submitting.value || !props.backlogItem) return
      errorMessage.value = validate()
      if (errorMessage.value) return

      submitting.value = true
      try {
        const payload = {
          backlog_item_id: props.backlogItem.id,
          supplier_name: form.supplier_name.trim(),
          quantity: Number(form.quantity),
          unit_cost: Number(form.unit_cost),
          expected_delivery_date: form.expected_delivery_date
        }
        const notes = form.notes.trim()
        if (notes) payload.notes = notes

        const created = await api.createPurchaseOrder(payload)
        Object.assign(form, emptyForm())
        emit('po-created', created)
      } catch (err) {
        errorMessage.value = err.response?.data?.detail || t('purchaseOrder.errors.createFailed')
      } finally {
        submitting.value = false
      }
    }

    const loadPO = async () => {
      loading.value = true
      try {
        po.value = await api.getPurchaseOrderByBacklogItem(props.backlogItem.id)
      } catch (err) {
        errorMessage.value = err.response?.data?.detail || t('purchaseOrder.errors.loadFailed')
      } finally {
        loading.value = false
      }
    }

    watch(() => props.isOpen, (open) => {
      if (!open) return
      Object.assign(form, emptyForm())
      form.quantity = shortage.value
      po.value = null
      errorMessage.value = ''
      submitting.value = false
      if (props.mode === 'view' && props.backlogItem) loadPO()
    })

    const close = () => emit('close')

    return { t, form, po, loading, submitting, errorMessage, shortage, money, formattedTotal, submit, close }
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-container {
  background: white;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  width: 90%;
  max-width: 600px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem 2rem;
  border-bottom: 2px solid #e2e8f0;
}

.modal-title {
  font-size: 1.5rem;
  font-weight: 600;
  color: #0f172a;
  margin: 0;
}

.close-button {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.close-button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.modal-body {
  padding: 2rem;
  overflow-y: auto;
  flex: 1;
}

.modal-footer {
  padding: 1.5rem 2rem;
  border-top: 2px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 1rem;
}

.btn-secondary {
  padding: 0.75rem 1.5rem;
  background: #f1f5f9;
  color: #475569;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-secondary:hover {
  background: #e2e8f0;
}

.btn-primary {
  padding: 0.75rem 1.5rem;
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s ease;
}

.btn-primary:hover:not(:disabled) {
  background: #1e293b;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.item-context {
  background: #f8fafc;
  border-radius: 12px;
  padding: 1rem 1.25rem;
  margin-bottom: 1.5rem;
}

.context-name {
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 0.25rem;
}

.context-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  font-size: 0.875rem;
  color: #64748b;
}

.po-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.form-row {
  display: flex;
  gap: 1rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  flex: 1;
}

label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #475569;
}

.po-input {
  padding: 0.75rem;
  border: 2px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.95rem;
  font-family: inherit;
  transition: border-color 0.2s ease;
  resize: vertical;
}

.po-input:focus {
  outline: none;
  border-color: #667eea;
}

.total-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 1rem;
  border-top: 1px solid #e2e8f0;
  color: #475569;
}

.total-row strong {
  font-size: 1.25rem;
  color: #0f172a;
}

.error-message {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #dc2626;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  font-size: 0.9rem;
}

.state-message {
  text-align: center;
  padding: 2rem;
  color: #64748b;
}

.po-details {
  margin: 0;
  display: flex;
  flex-direction: column;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.75rem 0;
  border-bottom: 1px solid #e2e8f0;
}

.detail-row:last-child {
  border-bottom: none;
}

.detail-row dt {
  color: #64748b;
  font-size: 0.875rem;
  font-weight: 600;
}

.detail-row dd {
  margin: 0;
  color: #0f172a;
  text-align: right;
  word-break: break-word;
}

.status-badge {
  display: inline-block;
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 0.8rem;
  font-weight: 600;
  text-transform: capitalize;
}
</style>
