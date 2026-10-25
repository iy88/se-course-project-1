/** 业务文案映射：状态/枚举到中文展示。 */

export const productStatusLabels = {
  pending_review: '待审核',
  rejected: '审核未通过',
  listed: '公开可交易',
  in_transaction: '交易中',
  delisted: '已下架',
}

export const tradeStatusLabels = {
  pending_acceptance: '待接受',
  rejected: '已拒绝',
  withdrawn: '已撤回',
  closed: '已关闭',
  in_progress: '进行中',
  disputed: '有争议',
  abnormal: '异常交易',
  terminated: '已终止',
  completed: '已完成',
}

export const caseTypeLabels = {
  product_review: '商品审核',
  report: '举报事项',
  trade_dispute: '交易争议',
  abnormal_trade: '异常交易',
  account_ban: '账户处置',
}

export const caseStatusLabels = {
  pending: '待认领',
  processing: '处理中',
  disposed: '已处置',
}

export const reportStatusLabels = {
  pending: '待处理',
  processing: '核查中',
  unfounded: '不予处理',
  handled: '已处置',
}

export function fen2yuan(cents) {
  return (cents / 100).toFixed(2)
}

export function fmtTime(value) {
  if (!value) return ''
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
