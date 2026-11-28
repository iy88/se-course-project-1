import { reactive, watch, type Ref } from "vue";
import type { TradeView } from "../../api/contracts";
import { toLocalInputValue } from "../../app/format";

export function useTradeAgreementDraft(trade: Ref<TradeView | null>) {
  const agreementForm = reactive({
    deliveryAt: "",
    place: "",
    method: "自提",
    amountYuan: "",
    paymentMethod: "当面支付",
    paymentTiming: "交付时",
  });

  watch(
    trade,
    (detail) => {
      if (!detail) return;
      const source = detail.agreement.pending ?? detail.agreement.current;
      if (source) {
        agreementForm.deliveryAt = toLocalInputValue(source.delivery_at);
        agreementForm.place = source.delivery_place_text;
        agreementForm.method = source.delivery_method;
        agreementForm.amountYuan = (source.amount_cents / 100).toFixed(2);
        agreementForm.paymentMethod = source.payment_method;
        agreementForm.paymentTiming = source.payment_timing;
      } else if (detail.product.price_cents && !agreementForm.amountYuan) {
        agreementForm.amountYuan = (detail.product.price_cents / 100).toFixed(2);
      }
    },
    { immediate: true },
  );

  return agreementForm;
}
