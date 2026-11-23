/*
 * In-memory state backing the simulated data source.
 *
 * The shapes mirror the agreed contracts closely enough that views cannot tell
 * the difference, and every mutation keeps the derived blocks (`permissions`,
 * `unread_count`, `unread_count` totals) consistent so the UI can be exercised
 * without a running backend.
 */
import type {
  Agreement,
  BannedScopeView,
  CancellationMode,
  CaseDetail,
  CaseKind,
  CaseMessageKind,
  CaseStatus,
  CategoryView,
  ConversationKind,
  DecisionKind,
  FilePurpose,
  MyOverview,
  ProductLifecycle,
  PublicCaseResult,
  ReviewStatus,
  SignedImage,
  TradeAction,
  TradeStatus,
  TradeView,
} from "../../api/contracts";

export interface MockAccount {
  account_id: string;
  email: string;
  password: string;
  display_name: string;
  roles: ("user" | "manager")[];
  avatar_file_id: string | null;
  write_restricted: boolean;
}

export interface MockFile {
  file_id: string;
  owner_account_id: string;
  purpose: FilePurpose;
  state: "uploading" | "verified";
  content_type: string;
  size_bytes: number;
  object_key: string;
  expires_at: string;
  verified_at: string | null;
  /** Simulated object URL; the signature is fake but stable while unexpired. */
  url: string;
}

export interface MockCategory {
  id: string;
  main_name: string;
  aliases: string[];
  disabled: boolean;
}

export interface MockProduct {
  id: string;
  seller_id: string;
  title: string;
  description: string;
  price_cents: number;
  category_ids: string[];
  image_file_ids: string[];
  lifecycle_state: ProductLifecycle;
  content_version: number;
  created_at: string;
  updated_at: string;
  pending_audit_id: string | null;
  pending_case_id: string | null;
  pending_submitted_at: string | null;
  latest_audit_id: string | null;
  latest_review_status: ReviewStatus | null;
  latest_review_reason: string | null;
  latest_review_decided_at: string | null;
  category_application: { application_id: string; proposed_name: string; status: string } | null;
  display_restrictions: { source_type: string; reason: string; created_at: string }[];
  edit_history: MockProductEdit[];
}

export interface MockProductEdit {
  edit_id: string;
  edited_at: string;
  operator_kind: string;
  edit_kind: string;
  before_content: Record<string, unknown>;
  after_content: Record<string, unknown>;
  reason: string | null;
}

export interface MockConfirmation {
  id: string;
  agreement_id: string;
  confirmer_id: string;
  note: string | null;
  submitted_at: string;
}

export interface MockTrade {
  id: string;
  product_id: string;
  buyer_id: string;
  seller_id: string;
  status: TradeStatus;
  phase: "first_agreement_pending" | "awaiting_completion" | null;
  terminal_reason: "completed" | "cancelled" | "admin_terminated" | null;
  request_note: string | null;
  requested_at: string;
  responded_at: string | null;
  close_reason: string | null;
  agreements: Agreement[];
  confirmations: MockConfirmation[];
  wait: {
    active: boolean;
    started_at: string | null;
    deadline_at: string | null;
    remaining_seconds: number;
    paused: boolean;
    ended_at: string | null;
    end_reason: string | null;
  };
  freeze: {
    id: string;
    source: string;
    source_ref: string | null;
    reason: string;
    started_at: string;
  }[];
  cancellation: {
    id: string;
    proposed_by: string;
    mode: CancellationMode;
    reason: string | null;
    status: "pending" | "accepted" | "rejected" | "withdrawn";
    proposed_at: string;
  } | null;
  dispute: {
    id: string;
    initiator_id: string;
    statement: string;
    status: "open" | "resolved" | "terminated";
    opened_at: string;
    resolved_at: string | null;
  } | null;
  trade_conversation_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  reviews: {
    review_id: string;
    reviewer_id: string;
    rating: number;
    content: string;
    created_at: string;
    visible: boolean;
  }[];
}

export interface MockConversation {
  conversation_id: string;
  kind: ConversationKind;
  participant_ids: string[];
  archived_at: string | null;
  created_at: string;
  source_ref: { resource_type: string; resource_id: string } | null;
}

export interface MockMessage {
  message_id: string;
  conversation_id: string;
  kind: ConversationKind;
  seq: number;
  sender_id: string | null;
  sender_kind: "user" | "system";
  message_type: string;
  body: string;
  created_at: string;
  case_message_kind?: CaseMessageKind;
}

export interface MockReadProgress {
  account_id: string;
  kind: ConversationKind;
  conversation_id: string;
  last_read_seq: number;
  updated_at: string;
}

export interface MockNotification {
  notification_id: string;
  recipient_id: string;
  event_type: string;
  occurred_at: string;
  read_at: string | null;
  summary: string;
  source: { resource_type: string; resource_id: string } | null;
}

export interface MockCase {
  case_id: string;
  case_type: CaseKind;
  status: CaseStatus;
  reporter_id: string | null;
  related_ids: string[];
  manager_id: string | null;
  claimed_at: string | null;
  decision_kind: CaseDetail["decision_kind"];
  reason_text: string | null;
  note: string | null;
  archived_at: string | null;
  appeal_deadline_at: string | null;
  public_result_at: string | null;
  created_at: string;
  updated_at: string;
  supplement_count: number;
  thread_id: string | null;
  actions: { action_kind: string; occurred_at: string; actor_kind: string }[];
  enforcements: { action: string; current_state: string }[];
  target: { target_type: string; target_id: string } | null;
  public_result: PublicCaseResult | null;
}

export interface MockState {
  currentAccountId: string | null;
  accounts: MockAccount[];
  files: MockFile[];
  categories: MockCategory[];
  products: MockProduct[];
  trades: MockTrade[];
  conversations: MockConversation[];
  messages: MockMessage[];
  readProgress: MockReadProgress[];
  notifications: MockNotification[];
  cases: MockCase[];
  bannedScope: BannedScopeView;
  idempotency: Map<string, unknown>;
  sequences: Record<string, number>;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Fixed "now" so seeded timestamps stay relative to a stable demo moment. */
export const DEMO_NOW = new Date("2026-11-20T09:00:00Z");

function iso(offsetMs: number): string {
  return new Date(DEMO_NOW.getTime() + offsetMs).toISOString();
}

export function nextId(state: MockState, scope: string): string {
  const next = (state.sequences[scope] ?? 0) + 1;
  state.sequences[scope] = next;
  return String(next);
}

export function createSeedState(): MockState {
  const state: MockState = {
    currentAccountId: "1",
    accounts: [],
    files: [],
    categories: [],
    products: [],
    trades: [],
    conversations: [],
    messages: [],
    readProgress: [],
    notifications: [],
    cases: [],
    bannedScope: { updated_at: iso(-6 * DAY), groups: [] },
    idempotency: new Map(),
    sequences: {},
  };

  state.accounts = [
    {
      account_id: "1",
      email: "lin@campus.example.edu",
      password: "Campus#2026",
      display_name: "林同学",
      roles: ["user"],
      avatar_file_id: null,
      write_restricted: false,
    },
    {
      account_id: "2",
      email: "zhao@campus.example.edu",
      password: "Campus#2026",
      display_name: "赵同学",
      roles: ["user"],
      avatar_file_id: null,
      write_restricted: false,
    },
    {
      account_id: "3",
      email: "qian@campus.example.edu",
      password: "Campus#2026",
      display_name: "钱同学",
      roles: ["user"],
      avatar_file_id: null,
      write_restricted: false,
    },
    {
      account_id: "4",
      email: "manager@campus.example.edu",
      password: "Campus#2026",
      display_name: "审核管理员",
      roles: ["user", "manager"],
      avatar_file_id: null,
      write_restricted: false,
    },
  ];
  state.sequences.accounts = 4;

  state.files = [
    {
      file_id: "11",
      owner_account_id: "1",
      purpose: "product_image",
      state: "verified",
      content_type: "image/jpeg",
      size_bytes: 182_400,
      object_key: "dev/product_image/seed-11.jpg",
      expires_at: iso(30 * DAY),
      verified_at: iso(-5 * DAY),
      url: "/api/v1/files/11/content",
    },
    {
      file_id: "12",
      owner_account_id: "1",
      purpose: "product_image",
      state: "verified",
      content_type: "image/jpeg",
      size_bytes: 214_100,
      object_key: "dev/product_image/seed-12.jpg",
      expires_at: iso(30 * DAY),
      verified_at: iso(-5 * DAY),
      url: "/api/v1/files/12/content",
    },
    {
      file_id: "13",
      owner_account_id: "1",
      purpose: "product_image",
      state: "verified",
      content_type: "image/png",
      size_bytes: 96_300,
      object_key: "dev/product_image/seed-13.png",
      expires_at: iso(30 * DAY),
      verified_at: iso(-5 * DAY),
      url: "/api/v1/files/13/content",
    },
    {
      file_id: "14",
      owner_account_id: "2",
      purpose: "case_evidence",
      state: "verified",
      content_type: "image/png",
      size_bytes: 46_800,
      object_key: "dev/case_evidence/seed-14.png",
      expires_at: iso(30 * DAY),
      verified_at: iso(-2 * DAY),
      url: "/api/v1/files/14/content",
    },
  ];
  state.sequences.files = 14;

  state.categories = [
    { id: "1", main_name: "教材", aliases: ["课本", "教辅"], disabled: false },
    { id: "2", main_name: "交通工具", aliases: ["自行车", "代步"], disabled: false },
    { id: "3", main_name: "生活电器", aliases: ["小家电"], disabled: false },
    { id: "4", main_name: "宿舍用品", aliases: ["寝室", "生活用品"], disabled: false },
    { id: "5", main_name: "体育器材", aliases: ["运动", "球类"], disabled: false },
    { id: "6", main_name: "乐器", aliases: [], disabled: true },
  ];
  state.sequences.categories = 6;

  state.bannedScope = {
    updated_at: iso(-6 * DAY),
    groups: [
      {
        group: "legal_prohibited",
        items: [
          { id: "1", content: "管制刀具、仿真枪及外观仿真实物和配件", display_order: 1 },
          { id: "2", content: "盗版、影印教材（含整本影印及扫描件）", display_order: 2 },
          { id: "3", content: "他人证件与实名材料（含学生证、身份证照片）", display_order: 3 },
        ],
      },
      {
        group: "dangerous_controlled",
        items: [
          { id: "4", content: "易燃易爆品与危险化学品（含实验室剩余试剂）", display_order: 1 },
        ],
      },
      {
        group: "live_animals",
        items: [{ id: "5", content: "活体动物（含宿舍饲养宠物）", display_order: 1 }],
      },
      {
        group: "medicine_device",
        items: [{ id: "6", content: "处方药与医疗器械（含开架处方药）", display_order: 1 }],
      },
      {
        group: "account_virtual",
        items: [{ id: "7", content: "账号、会员与虚拟资产（含租借校园账号）", display_order: 1 }],
      },
      {
        group: "service_promotion",
        items: [{ id: "8", content: "代写、代考与学习服务推广", display_order: 1 }],
      },
      { group: "other", items: [] },
    ],
  };

  state.products = [
    {
      id: "1",
      seller_id: "1",
      title: "《高等数学》第七版 上下册",
      description: "九成新，上册有少量铅笔批注，下册几乎全新。含习题册。",
      price_cents: 4500,
      category_ids: ["1"],
      image_file_ids: ["11", "12"],
      lifecycle_state: "public",
      content_version: 2,
      created_at: iso(-8 * DAY),
      updated_at: iso(-3 * DAY),
      pending_audit_id: null,
      pending_case_id: null,
      pending_submitted_at: null,
      latest_audit_id: "A-1001",
      latest_review_status: "passed",
      latest_review_reason: null,
      latest_review_decided_at: iso(-7 * DAY),
      category_application: null,
      display_restrictions: [],
      edit_history: [],
    },
    {
      id: "2",
      seller_id: "1",
      title: "校园通勤自行车 26 寸",
      description: "骑行两年，刹车和链条已上油，赠车锁。",
      price_cents: 18_000,
      category_ids: ["2"],
      image_file_ids: ["13"],
      lifecycle_state: "in_trade",
      content_version: 1,
      created_at: iso(-12 * DAY),
      updated_at: iso(-2 * DAY),
      pending_audit_id: null,
      pending_case_id: null,
      pending_submitted_at: null,
      latest_audit_id: "A-1002",
      latest_review_status: "passed",
      latest_review_reason: null,
      latest_review_decided_at: iso(-11 * DAY),
      category_application: null,
      display_restrictions: [],
      edit_history: [],
    },
    {
      id: "3",
      seller_id: "1",
      title: "护眼台灯（暖光可调）",
      description: "宿舍用台灯，三档亮度，含原装电源。",
      price_cents: 3500,
      category_ids: ["3", "4"],
      image_file_ids: [],
      lifecycle_state: "pending_review",
      content_version: 1,
      created_at: iso(-1 * DAY),
      updated_at: iso(-1 * DAY),
      pending_audit_id: "A-1003",
      pending_case_id: "6",
      pending_submitted_at: iso(-1 * DAY),
      latest_audit_id: "A-1003",
      latest_review_status: "pending",
      latest_review_reason: null,
      latest_review_decided_at: null,
      category_application: null,
      display_restrictions: [],
      edit_history: [],
    },
    {
      id: "4",
      seller_id: "1",
      title: "《线性代数》同济版 笔记齐全",
      description: "教材本身完好，附本人手写笔记。",
      price_cents: 2000,
      category_ids: ["1"],
      image_file_ids: [],
      lifecycle_state: "review_rejected",
      content_version: 3,
      created_at: iso(-6 * DAY),
      updated_at: iso(-4 * DAY),
      pending_audit_id: null,
      pending_case_id: null,
      pending_submitted_at: null,
      latest_audit_id: "A-1004",
      latest_review_status: "rejected",
      latest_review_reason: "封面图片含盗版影印页面，请更换为原书实物照片后重新提交。",
      latest_review_decided_at: iso(-4 * DAY),
      category_application: {
        application_id: "CA-1",
        proposed_name: "考研资料",
        status: "pending",
      },
      display_restrictions: [],
      edit_history: [],
    },
    {
      id: "5",
      seller_id: "1",
      title: "宿舍小台灯（已下架）",
      description: "已另售，暂时下架。",
      price_cents: 1500,
      category_ids: ["4"],
      image_file_ids: [],
      lifecycle_state: "off_shelf",
      content_version: 2,
      created_at: iso(-20 * DAY),
      updated_at: iso(-9 * DAY),
      pending_audit_id: null,
      pending_case_id: null,
      pending_submitted_at: null,
      latest_audit_id: "A-1005",
      latest_review_status: "passed",
      latest_review_reason: null,
      latest_review_decided_at: iso(-19 * DAY),
      category_application: null,
      display_restrictions: [],
      edit_history: [],
    },
    {
      id: "6",
      seller_id: "2",
      title: "考研英语真题（2010—2024）",
      description: "含解析，部分页面有荧光笔标记。",
      price_cents: 3000,
      category_ids: ["1"],
      image_file_ids: [],
      lifecycle_state: "public",
      content_version: 1,
      created_at: iso(-4 * DAY),
      updated_at: iso(-4 * DAY),
      pending_audit_id: null,
      pending_case_id: null,
      pending_submitted_at: null,
      latest_audit_id: "A-1006",
      latest_review_status: "passed",
      latest_review_reason: null,
      latest_review_decided_at: iso(-3 * DAY),
      category_application: null,
      display_restrictions: [],
      edit_history: [],
    },
    {
      id: "7",
      seller_id: "3",
      title: "羽毛球拍 双拍装",
      description: "用过一个学期，拍线完好，含拍套。",
      price_cents: 8000,
      category_ids: ["5"],
      image_file_ids: [],
      lifecycle_state: "public",
      content_version: 1,
      created_at: iso(-2 * DAY),
      updated_at: iso(-2 * DAY),
      pending_audit_id: null,
      pending_case_id: null,
      pending_submitted_at: null,
      latest_audit_id: "A-1007",
      latest_review_status: "passed",
      latest_review_reason: null,
      latest_review_decided_at: iso(-1 * DAY),
      category_application: null,
      display_restrictions: [],
      edit_history: [],
    },
    {
      // Withdrawn after a rejected review: off shelf, and not re-listable.
      id: "8",
      seller_id: "1",
      title: "旧款耳机（审核未通过）",
      description: "线材老化，已下架。",
      price_cents: 2500,
      category_ids: ["3"],
      image_file_ids: [],
      lifecycle_state: "off_shelf",
      content_version: 2,
      created_at: iso(-14 * DAY),
      updated_at: iso(-11 * DAY),
      pending_audit_id: null,
      pending_case_id: null,
      pending_submitted_at: null,
      latest_audit_id: "A-1008",
      latest_review_status: "rejected",
      latest_review_reason: "标题与描述含夸大功效表述，请修改后重新提交审核。",
      latest_review_decided_at: iso(-11 * DAY),
      category_application: null,
      display_restrictions: [],
      edit_history: [],
    },
  ];
  state.sequences.products = 8;

  state.conversations = [
    {
      conversation_id: "1",
      kind: "chat",
      participant_ids: ["1", "2"],
      archived_at: null,
      created_at: iso(-10 * DAY),
      source_ref: null,
    },
    {
      conversation_id: "1",
      kind: "trade",
      participant_ids: ["1", "2"],
      archived_at: null,
      created_at: iso(-2 * DAY),
      source_ref: { resource_type: "trade", resource_id: "1" },
    },
    {
      conversation_id: "2",
      kind: "trade",
      participant_ids: ["1", "3"],
      archived_at: null,
      created_at: iso(-1 * DAY),
      source_ref: { resource_type: "trade", resource_id: "2" },
    },
    {
      conversation_id: "1",
      kind: "case",
      participant_ids: ["1", "4"],
      archived_at: null,
      created_at: iso(-1 * DAY),
      source_ref: { resource_type: "case", resource_id: "6" },
    },
  ];
  state.sequences.conversations = 6;

  state.messages = [
    {
      message_id: "1",
      conversation_id: "1",
      kind: "chat",
      seq: 1,
      sender_id: "2",
      sender_kind: "user",
      message_type: "text",
      body: "同学你好，自行车还在吗？",
      created_at: iso(-10 * DAY),
    },
    {
      message_id: "2",
      conversation_id: "1",
      kind: "chat",
      seq: 2,
      sender_id: "1",
      sender_kind: "user",
      message_type: "text",
      body: "在的，车况不错，可以约时间看车。",
      created_at: iso(-10 * DAY + 5 * MINUTE),
    },
    {
      message_id: "3",
      conversation_id: "1",
      kind: "chat",
      seq: 3,
      sender_id: "2",
      sender_kind: "user",
      message_type: "text",
      body: "好的，我提交了购买请求，麻烦看下。",
      created_at: iso(-2 * DAY),
    },
    {
      message_id: "4",
      conversation_id: "1",
      kind: "trade",
      seq: 1,
      sender_id: null,
      sender_kind: "system",
      message_type: "system",
      body: "交易已建立：赵同学提交的购买请求已被接受。",
      created_at: iso(-2 * DAY),
    },
    {
      message_id: "5",
      conversation_id: "1",
      kind: "trade",
      seq: 2,
      sender_id: "2",
      sender_kind: "user",
      message_type: "text",
      body: "我周末在校，随时可以取车。",
      created_at: iso(-2 * DAY + 20 * MINUTE),
    },
    {
      message_id: "6",
      conversation_id: "2",
      kind: "trade",
      seq: 1,
      sender_id: null,
      sender_kind: "system",
      message_type: "system",
      body: "交易已建立：钱同学提交的购买请求已被接受。",
      created_at: iso(-1 * DAY),
    },
    {
      message_id: "7",
      conversation_id: "2",
      kind: "trade",
      seq: 2,
      sender_id: "3",
      sender_kind: "user",
      message_type: "text",
      body: "台灯可以今晚取吗？",
      created_at: iso(-1 * DAY + 30 * MINUTE),
    },
    {
      message_id: "8",
      conversation_id: "1",
      kind: "case",
      seq: 1,
      sender_id: "4",
      sender_kind: "user",
      message_type: "inquiry",
      body: "请说明该台灯的实际亮度档位与使用时长。",
      created_at: iso(-1 * DAY),
      case_message_kind: "inquiry",
    },
  ];
  state.sequences.messages = 8;

  state.readProgress = [
    {
      account_id: "1",
      kind: "chat",
      conversation_id: "1",
      last_read_seq: 2,
      updated_at: iso(-9 * DAY),
    },
    {
      account_id: "1",
      kind: "trade",
      conversation_id: "1",
      last_read_seq: 2,
      updated_at: iso(-2 * DAY),
    },
    {
      account_id: "1",
      kind: "trade",
      conversation_id: "2",
      last_read_seq: 1,
      updated_at: iso(-1 * DAY),
    },
  ];

  const agreement1: Agreement = {
    id: "1",
    base_agreement_id: null,
    version_no: 1,
    status: "effective",
    proposed_by: "1",
    delivery_at: iso(2 * DAY),
    delivery_place_text: "三号宿舍楼下",
    delivery_method: "自提",
    amount_cents: 18_000,
    payment_method: "当面支付",
    payment_timing: "交付时",
    proposed_at: iso(-2 * DAY + 10 * MINUTE),
  };
  const agreement2: Agreement = {
    id: "2",
    base_agreement_id: null,
    version_no: 1,
    status: "proposed",
    proposed_by: "1",
    delivery_at: iso(1 * DAY),
    delivery_place_text: "东门快递点",
    delivery_method: "约定地点交接",
    amount_cents: 3500,
    payment_method: "线上转账后自取",
    payment_timing: "交付前",
    proposed_at: iso(-1 * DAY + HOUR),
  };

  state.trades = [
    {
      id: "1",
      product_id: "2",
      buyer_id: "2",
      seller_id: "1",
      status: "in_progress",
      phase: "awaiting_completion",
      terminal_reason: null,
      request_note: "周末取，可以现金",
      requested_at: iso(-2 * DAY),
      responded_at: iso(-2 * DAY + 5 * MINUTE),
      close_reason: null,
      agreements: [agreement1],
      confirmations: [
        {
          id: "1",
          agreement_id: "1",
          confirmer_id: "1",
          note: "已交付并收到现金",
          submitted_at: iso(-1 * DAY),
        },
      ],
      wait: {
        active: true,
        started_at: iso(-1 * DAY),
        deadline_at: iso(6 * DAY),
        remaining_seconds: 6 * 24 * 3600,
        paused: false,
        ended_at: null,
        end_reason: null,
      },
      freeze: [],
      cancellation: null,
      dispute: null,
      trade_conversation_id: "1",
      version: 5,
      created_at: iso(-2 * DAY),
      updated_at: iso(-1 * DAY),
      reviews: [],
    },
    {
      id: "2",
      product_id: "3",
      buyer_id: "3",
      seller_id: "1",
      status: "in_progress",
      phase: "first_agreement_pending",
      terminal_reason: null,
      request_note: "台灯可以今晚取吗？",
      requested_at: iso(-1 * DAY),
      responded_at: iso(-1 * DAY + 10 * MINUTE),
      close_reason: null,
      agreements: [agreement2],
      confirmations: [],
      wait: {
        active: false,
        started_at: null,
        deadline_at: null,
        remaining_seconds: 0,
        paused: false,
        ended_at: null,
        end_reason: null,
      },
      freeze: [],
      cancellation: null,
      dispute: null,
      trade_conversation_id: "2",
      version: 3,
      created_at: iso(-1 * DAY),
      updated_at: iso(-1 * DAY + HOUR),
      reviews: [],
    },
    {
      id: "3",
      product_id: "1",
      buyer_id: "2",
      seller_id: "1",
      status: "completed",
      phase: null,
      terminal_reason: "completed",
      request_note: "教材还在吗？想整套收",
      requested_at: iso(-9 * DAY),
      responded_at: iso(-9 * DAY + 12 * MINUTE),
      close_reason: null,
      agreements: [
        {
          id: "3",
          base_agreement_id: null,
          version_no: 1,
          status: "effective",
          proposed_by: "2",
          delivery_at: iso(-8 * DAY),
          delivery_place_text: "图书馆一层",
          delivery_method: "约定地点交接",
          amount_cents: 4500,
          payment_method: "当面支付",
          payment_timing: "交付时",
          proposed_at: iso(-9 * DAY + 20 * MINUTE),
        },
      ],
      confirmations: [
        {
          id: "2",
          agreement_id: "3",
          confirmer_id: "2",
          note: null,
          submitted_at: iso(-8 * DAY),
        },
        {
          id: "3",
          agreement_id: "3",
          confirmer_id: "1",
          note: null,
          submitted_at: iso(-8 * DAY + HOUR),
        },
      ],
      wait: {
        active: false,
        started_at: null,
        deadline_at: null,
        remaining_seconds: 0,
        paused: false,
        ended_at: iso(-8 * DAY),
        end_reason: "both_confirmed",
      },
      freeze: [],
      cancellation: null,
      dispute: null,
      trade_conversation_id: null,
      version: 9,
      created_at: iso(-9 * DAY),
      updated_at: iso(-8 * DAY),
      reviews: [],
    },
    {
      id: "4",
      product_id: "2",
      buyer_id: "3",
      seller_id: "1",
      status: "rejected",
      phase: null,
      terminal_reason: null,
      request_note: "想看看车",
      requested_at: iso(-3 * DAY),
      responded_at: iso(-3 * DAY + 40 * MINUTE),
      close_reason: null,
      agreements: [],
      confirmations: [],
      wait: {
        active: false,
        started_at: null,
        deadline_at: null,
        remaining_seconds: 0,
        paused: false,
        ended_at: null,
        end_reason: null,
      },
      freeze: [],
      cancellation: null,
      dispute: null,
      trade_conversation_id: null,
      version: 3,
      created_at: iso(-3 * DAY),
      updated_at: iso(-3 * DAY + 40 * MINUTE),
      reviews: [],
    },
  ];
  state.sequences.trades = 4;
  state.sequences.agreements = 3;
  state.sequences.confirmations = 3;

  state.notifications = [
    {
      notification_id: "1",
      recipient_id: "1",
      event_type: "product_audit.passed",
      occurred_at: iso(-7 * DAY),
      read_at: iso(-6 * DAY),
      summary: "商品《高等数学》第七版 上下册已通过审核，现已公开可交易。",
      source: { resource_type: "product", resource_id: "1" },
    },
    {
      notification_id: "2",
      recipient_id: "1",
      event_type: "product_audit.rejected",
      occurred_at: iso(-4 * DAY),
      read_at: null,
      summary: "商品《线性代数》同济版 笔记齐全未通过审核：封面图片含盗版影印页面。",
      source: { resource_type: "product", resource_id: "4" },
    },
    {
      notification_id: "3",
      recipient_id: "1",
      event_type: "trade.request_accepted",
      occurred_at: iso(-2 * DAY),
      read_at: null,
      summary: "赵同学已接受《校园通勤自行车 26 寸》的交易请求，请在交易详情中提出约定。",
      source: { resource_type: "trade", resource_id: "1" },
    },
    {
      notification_id: "4",
      recipient_id: "1",
      event_type: "case.inquiry_created",
      occurred_at: iso(-1 * DAY),
      read_at: null,
      summary: "管理员就《护眼台灯（暖光可调）》发起问询，请在「我的事项」中回复。",
      source: { resource_type: "case", resource_id: "6" },
    },
    {
      notification_id: "5",
      recipient_id: "1",
      event_type: "trade.completion_submitted",
      occurred_at: iso(-1 * DAY + HOUR),
      read_at: iso(-1 * DAY + 2 * HOUR),
      summary: "钱同学已提交《护眼台灯（暖光可调）》的约定，等待你回应。",
      source: { resource_type: "trade", resource_id: "2" },
    },
  ];
  state.sequences.notifications = 5;

  state.cases = [
    {
      case_id: "5",
      case_type: "report",
      status: "claimed",
      reporter_id: "1",
      related_ids: ["2"],
      manager_id: "4",
      claimed_at: iso(-2 * DAY),
      decision_kind: null,
      reason_text: "对方在会话中反复发送与交易无关的广告内容。",
      note: "原始举报说明：会话内多次发送外部链接。",
      archived_at: null,
      appeal_deadline_at: null,
      public_result_at: null,
      created_at: iso(-3 * DAY),
      updated_at: iso(-2 * DAY),
      supplement_count: 1,
      thread_id: null,
      actions: [
        { action_kind: "submit", occurred_at: iso(-3 * DAY), actor_kind: "reporter" },
        {
          action_kind: "supplement",
          occurred_at: iso(-2 * DAY + 2 * HOUR),
          actor_kind: "reporter",
        },
        { action_kind: "claim", occurred_at: iso(-2 * DAY), actor_kind: "manager" },
      ],
      enforcements: [],
      target: { target_type: "message", target_id: "3" },
      public_result: null,
    },
    {
      case_id: "6",
      case_type: "product_review",
      status: "claimed",
      reporter_id: null,
      related_ids: ["1"],
      manager_id: "4",
      claimed_at: iso(-1 * DAY),
      decision_kind: null,
      reason_text: "商品《护眼台灯（暖光可调）》待审核。",
      note: null,
      archived_at: null,
      appeal_deadline_at: null,
      public_result_at: null,
      created_at: iso(-1 * DAY),
      updated_at: iso(-1 * DAY),
      supplement_count: 0,
      thread_id: "1",
      actions: [
        { action_kind: "submit", occurred_at: iso(-1 * DAY), actor_kind: "seller" },
        { action_kind: "claim", occurred_at: iso(-1 * DAY), actor_kind: "manager" },
        { action_kind: "inquire", occurred_at: iso(-1 * DAY), actor_kind: "manager" },
      ],
      enforcements: [],
      target: { target_type: "product", target_id: "3" },
      public_result: null,
    },
    {
      case_id: "7",
      case_type: "report",
      status: "decided",
      reporter_id: null,
      related_ids: ["1"],
      manager_id: "4",
      claimed_at: iso(-12 * DAY),
      decision_kind: "violation",
      reason_text: "经核实存在违规推广行为，已对相关商品作出下架处理。",
      note: null,
      archived_at: iso(-10 * DAY),
      appeal_deadline_at: null,
      public_result_at: iso(-10 * DAY),
      created_at: iso(-13 * DAY),
      updated_at: iso(-10 * DAY),
      supplement_count: 0,
      thread_id: null,
      actions: [
        { action_kind: "submit", occurred_at: iso(-13 * DAY), actor_kind: "reporter" },
        { action_kind: "claim", occurred_at: iso(-12 * DAY), actor_kind: "manager" },
        { action_kind: "decide", occurred_at: iso(-11 * DAY), actor_kind: "manager" },
        { action_kind: "close", occurred_at: iso(-10 * DAY), actor_kind: "manager" },
      ],
      enforcements: [{ action: "take_product_off_shelf", current_state: "active" }],
      target: { target_type: "product", target_id: "5" },
      public_result: {
        case_id: "7",
        decision_kind: "violation",
        public_summary: "被举报商品存在违规推广内容。",
        public_reason: "经核实违反平台禁发范围，已下架处理。",
        published_at: iso(-10 * DAY),
      },
    },
  ];
  state.sequences.cases = 7;

  return state;
}

/* ------------------------------------------------------- derived projections */

export function accountRef(
  state: MockState,
  accountId: string,
): {
  id: string;
  display_name: string;
  avatar_url: string | null;
} {
  const account = state.accounts.find((item) => item.account_id === accountId);
  const file = account?.avatar_file_id
    ? state.files.find((item) => item.file_id === account.avatar_file_id)
    : undefined;
  return {
    id: accountId,
    display_name: account?.display_name ?? "已注销账户",
    avatar_url: file?.url ?? null,
  };
}

export function signedImage(state: MockState, fileId: string): SignedImage | null {
  const file = state.files.find((item) => item.file_id === fileId);
  if (!file) return null;
  return { file_id: file.file_id, url: file.url, expires_at: file.expires_at };
}

export function categoryView(state: MockState, category: MockCategory): CategoryView {
  const hasPublic = state.products.some(
    (product) => product.lifecycle_state === "public" && product.category_ids.includes(category.id),
  );
  return {
    id: category.id,
    main_name: category.main_name,
    aliases: category.aliases,
    selectable: !category.disabled,
    has_public_products: hasPublic,
  };
}

export function categoryRefs(state: MockState, ids: string[]): { id: string; name: string }[] {
  return ids
    .map((id) => state.categories.find((category) => category.id === id))
    .filter((category): category is MockCategory => Boolean(category))
    .map((category) => ({ id: category.id, name: category.main_name }));
}

/** Actions the current viewer may perform, derived from trade state. */
export function tradeActions(trade: MockTrade, viewerId: string): TradeAction[] {
  const isBuyer = trade.buyer_id === viewerId;
  const isSeller = trade.seller_id === viewerId;
  if (!isBuyer && !isSeller) return [];

  const actions: TradeAction[] = [];
  const current = trade.agreements.find((item) => item.status === "effective") ?? null;
  const pending = trade.agreements.find((item) => item.status === "proposed") ?? null;
  const viewerConfirmed = trade.confirmations.some(
    (item) => item.confirmer_id === viewerId && item.agreement_id === current?.id,
  );

  switch (trade.status) {
    case "pending_acceptance":
      if (isSeller) actions.push("accept", "reject");
      if (isBuyer) actions.push("withdraw");
      break;
    case "in_progress":
      if (trade.phase === "first_agreement_pending" && !pending) {
        actions.push("propose_agreement");
      }
      if (pending && pending.proposed_by !== viewerId) actions.push("decide_agreement");
      if (pending && pending.proposed_by === viewerId) actions.push("decide_agreement");
      if (trade.phase === "awaiting_completion" && !viewerConfirmed) {
        actions.push("submit_completion");
      }
      if (!trade.cancellation) actions.push("propose_cancellation");
      if (trade.cancellation && trade.cancellation.proposed_by !== viewerId) {
        actions.push("decide_cancellation");
      }
      if (trade.cancellation && trade.cancellation.proposed_by === viewerId) {
        actions.push("decide_cancellation");
      }
      if (current && !trade.dispute) actions.push("open_dispute");
      actions.push("open_trade_conversation");
      break;
    case "disputed":
      if (trade.dispute?.status === "resolved") actions.push("confirm_dispute_resolution");
      actions.push("open_trade_conversation");
      break;
    case "completed":
      if (!trade.reviews.some((review) => review.reviewer_id === viewerId)) {
        actions.push("submit_review");
      }
      break;
    default:
      break;
  }

  if (trade.trade_conversation_id && trade.status !== "completed") {
    if (!actions.includes("open_trade_conversation")) actions.push("open_trade_conversation");
  }

  return actions;
}

export function tradeView(state: MockState, trade: MockTrade, viewerId: string): TradeView {
  const product = state.products.find((item) => item.id === trade.product_id);
  const current = trade.agreements.find((item) => item.status === "effective") ?? null;
  const pending = trade.agreements.find((item) => item.status === "proposed") ?? null;
  return {
    id: trade.id,
    product: {
      id: trade.product_id,
      title: product?.title,
      price_cents: product?.price_cents,
    },
    buyer: accountRef(state, trade.buyer_id),
    seller: accountRef(state, trade.seller_id),
    status: trade.status,
    phase: trade.phase,
    terminal_reason: trade.terminal_reason,
    request: {
      note: trade.request_note,
      requested_at: trade.requested_at,
      responded_at: trade.responded_at,
      close_reason: trade.close_reason,
    },
    agreement: { current, pending },
    confirmations: {
      current: current
        ? trade.confirmations.filter((item) => item.agreement_id === current.id)
        : [],
      both_current: Boolean(
        current &&
        trade.confirmations.some(
          (item) => item.agreement_id === current.id && item.confirmer_id === trade.buyer_id,
        ) &&
        trade.confirmations.some(
          (item) => item.agreement_id === current.id && item.confirmer_id === trade.seller_id,
        ),
      ),
    },
    wait: trade.wait,
    freeze: { active: trade.freeze.length > 0, items: trade.freeze },
    cancellation: { pending: trade.cancellation },
    dispute: { open: trade.dispute },
    trade_conversation_id: trade.trade_conversation_id,
    version: trade.version,
    permissions: { allowed_actions: tradeActions(trade, viewerId) },
    created_at: trade.created_at,
    updated_at: trade.updated_at,
    agreement_history: trade.agreements.filter((item) => item.status !== "proposed"),
  };
}

export function unreadCount(
  state: MockState,
  accountId: string,
  kind: ConversationKind,
  conversationId: string,
): number {
  const lastRead =
    state.readProgress.find(
      (item) =>
        item.account_id === accountId &&
        item.kind === kind &&
        item.conversation_id === conversationId,
    )?.last_read_seq ?? 0;
  return state.messages.filter(
    (message) =>
      message.kind === kind &&
      message.conversation_id === conversationId &&
      message.seq > lastRead &&
      message.sender_id !== accountId &&
      message.sender_kind !== "system",
  ).length;
}

export function overview(state: MockState, accountId: string): MyOverview {
  const products = state.products.filter((item) => item.seller_id === accountId);
  const trades = state.trades.filter(
    (item) => item.buyer_id === accountId || item.seller_id === accountId,
  );
  const byState: Record<string, number> = {};
  for (const product of products) {
    byState[product.lifecycle_state] = (byState[product.lifecycle_state] ?? 0) + 1;
  }
  const tradeByState: Record<string, number> = {};
  for (const trade of trades) {
    tradeByState[trade.status] = (tradeByState[trade.status] ?? 0) + 1;
  }
  const written = state.trades
    .flatMap((trade) => trade.reviews)
    .filter((review) => review.reviewer_id === accountId).length;
  const received = state.trades
    .filter((trade) => trade.buyer_id === accountId || trade.seller_id === accountId)
    .flatMap((trade) => trade.reviews)
    .filter((review) => review.reviewer_id !== accountId).length;
  const submittedCases = state.cases.filter((item) => item.reporter_id === accountId).length;
  const receivedCases = state.cases.filter(
    (item) => item.reporter_id !== accountId && item.decision_kind !== null,
  ).length;

  return {
    as_of: new Date().toISOString(),
    products: { total: products.length, by_state: byState },
    trades: {
      total: trades.length,
      buying: trades.filter((item) => item.buyer_id === accountId).length,
      selling: trades.filter((item) => item.seller_id === accountId).length,
      by_state: tradeByState,
    },
    favorites: { total: 0, valid: 0, invalid: 0 },
    evaluations: { written, received },
    reports: { submitted: submittedCases, received: receivedCases },
    todo_count: todoCount(state, accountId),
  };
}

export function todoCount(state: MockState, accountId: string): number {
  let count = 0;
  for (const trade of state.trades) {
    if (trade.seller_id === accountId && trade.status === "pending_acceptance") count += 1;
    const pending = trade.agreements.find((item) => item.status === "proposed");
    if (pending && pending.proposed_by !== accountId && trade.status === "in_progress") {
      count += 1;
    }
    if (trade.status === "in_progress" && trade.cancellation?.proposed_by !== accountId) {
      if (trade.cancellation) count += 1;
    }
  }
  for (const item of state.cases) {
    if (item.related_ids.includes(accountId) && item.status !== "decided") count += 1;
  }
  return count;
}

export function caseDetail(item: MockCase): CaseDetail {
  return {
    case_id: item.case_id,
    case_type: item.case_type,
    case_status: item.status,
    decision_kind: item.decision_kind,
    archived_at: item.archived_at,
    reason_text: item.reason_text,
    thread: item.thread_id ? { conversation_kind: "case", conversation_id: item.thread_id } : null,
    appeal_deadline_at: item.appeal_deadline_at,
    actions: item.actions,
    enforcements: item.enforcements,
    public_result_at: item.public_result_at,
  };
}

export function decideDecision(trade: MockTrade, decision: DecisionKind): void {
  trade.updated_at = new Date().toISOString();
  trade.version += 1;
  if (decision === "withdraw") {
    trade.status = "withdrawn";
    return;
  }
  if (decision === "reject") {
    trade.status = "rejected";
    return;
  }
  trade.status = "in_progress";
  trade.phase = "first_agreement_pending";
}
