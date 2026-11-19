<script setup lang="ts">
import axios from "axios";
import { computed, onMounted, ref } from "vue";

type Purpose = "product_image" | "case_evidence";
type Limit = { maxBytes: number; allowedContentTypes: string[] };
type Upload = { fileId: string; upload: { url: string; fields: Record<string, string> } };
type FileState = "uploading" | "verified" | "cleaning" | "deleted";
type ListedFile = {
  fileId: string;
  purpose: Purpose;
  state: FileState;
  referenceId: string | null;
};
const purposeLabels: Record<Purpose, string> = {
  product_image: "商品图片",
  case_evidence: "事项证据",
};
const stateLabels: Record<FileState, string> = {
  uploading: "待核验",
  verified: "已核验",
  cleaning: "回收中",
  deleted: "已回收",
};
type ReadUrl = { url: string; expiresAt: string };

const api = axios.create({
  baseURL: "/__dev/file-probe",
  adapter: "xhr",
  headers: { "X-File-Probe": "1" },
  timeout: 60_000,
});
const purpose = ref<Purpose>("product_image");
const limits = ref<Record<Purpose, Limit>>();
const limit = computed(() => limits.value?.[purpose.value]);
const input = ref<HTMLInputElement>();
const files = ref<ListedFile[]>();
const signed = ref<ReadUrl & { fileId: string }>();
const busy = ref(false);
const status = ref("");
const error = ref("");

async function run(step: string, action: () => Promise<void>) {
  busy.value = true;
  error.value = "";
  status.value = step;
  try {
    await action();
  } catch (failure) {
    status.value = "";
    if (axios.isAxiosError<{ code?: string }>(failure)) {
      error.value =
        failure.response?.data?.code ??
        (failure.response ? `HTTP ${failure.response.status}` : failure.message);
    } else {
      error.value = failure instanceof Error ? failure.message : "操作失败";
    }
  } finally {
    busy.value = false;
  }
}

async function loadFiles() {
  files.value = (await api.get<ListedFile[]>("/uploads")).data;
}

async function loadPage() {
  await run("读取文件", async () => {
    await Promise.all([
      loadFiles(),
      limits.value
        ? Promise.resolve()
        : api.get<Record<Purpose, Limit>>("/limits").then(({ data }) => (limits.value = data)),
    ]);
    status.value = "";
  });
}

async function uploadFile() {
  const file = input.value?.files?.[0];
  const selectedLimit = limit.value;
  if (!file || !selectedLimit) return;
  const contentType = file.type === "image/jpg" ? "image/jpeg" : file.type;

  await run("申请上传", async () => {
    if (file.size === 0 || file.size > selectedLimit.maxBytes) throw new Error("文件大小超出范围");
    if (!selectedLimit.allowedContentTypes.includes(contentType)) throw new Error("文件格式不支持");

    const { data } = await api.post<Upload>("/uploads", {
      purpose: purpose.value,
      size: file.size,
      contentType,
    });
    files.value = [
      { fileId: data.fileId, purpose: purpose.value, state: "uploading", referenceId: null },
      ...(files.value ?? []),
    ];

    status.value = "上传到 OSS";
    const body = new FormData();
    for (const [key, value] of Object.entries(data.upload.fields)) body.append(key, value);
    body.append("file", file);
    await axios.post(data.upload.url, body, {
      adapter: "xhr",
      timeout: 5 * 60_000,
    });
    if (input.value) input.value.value = "";
    status.value = "上传完成";
  });
}

async function complete(fileId: string) {
  await run("核验并建立测试引用", async () => {
    await api.post(`/uploads/${fileId}/complete`);
    await loadFiles();
    status.value = "核验通过";
  });
}

async function prepareRead(fileId: string) {
  await run("签发读取地址", async () => {
    const { data } = await api.get<ReadUrl>(`/uploads/${fileId}/read`);
    signed.value = { ...data, fileId };
    status.value = "";
  });
}

async function release(file: ListedFile) {
  if (!file.referenceId) return;
  await run("释放引用", async () => {
    await api.post(`/references/${file.referenceId}/release`);
    if (signed.value?.fileId === file.fileId) signed.value = undefined;
    await loadFiles();
    status.value = "引用已释放";
  });
}

onMounted(loadPage);
</script>

<template>
  <main class="page page--admin">
    <h1>文件服务测试</h1>
    <section class="probe">
      <form method="post" @submit.prevent="uploadFile">
        <fieldset :disabled="busy || !limits || !files">
          <legend>用途</legend>
          <label>
            <input v-model="purpose" type="radio" name="purpose" value="product_image" />
            商品图片
          </label>
          <label>
            <input v-model="purpose" type="radio" name="purpose" value="case_evidence" />
            事项证据
          </label>
        </fieldset>
        <div class="file-field">
          <label for="file">
            文件<span v-if="limit">（{{ limit.maxBytes / 1_048_576 }} MiB）</span>
          </label>
          <input
            id="file"
            ref="input"
            name="file"
            type="file"
            required
            :disabled="busy || !limits || !files"
            :accept="limit?.allowedContentTypes.join(',')"
          />
          <button type="submit" :disabled="busy || !limits || !files">直传 OSS</button>
        </div>
      </form>
      <p role="status">{{ status }}</p>
      <p v-if="error" role="alert">{{ error }}</p>
    </section>
    <section class="probe file-list">
      <div class="list-header">
        <h2 id="files-heading">文件列表</h2>
        <button type="button" :disabled="busy" @click="loadPage">刷新</button>
      </div>
      <div
        v-if="files?.length"
        class="table-scroll"
        role="region"
        aria-labelledby="files-heading"
        tabindex="0"
      >
        <table>
          <thead>
            <tr>
              <th scope="col">文件 ID</th>
              <th scope="col">用途</th>
              <th scope="col">状态</th>
              <th scope="col">引用 ID</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="file in files" :key="file.fileId">
              <th scope="row">{{ file.fileId }}</th>
              <td>{{ purposeLabels[file.purpose] }}</td>
              <td>{{ stateLabels[file.state] }}</td>
              <td>{{ file.referenceId ?? "—" }}</td>
              <td>
                <div class="actions">
                  <button
                    v-if="file.state === 'uploading'"
                    type="button"
                    :disabled="busy"
                    @click="complete(file.fileId)"
                  >
                    完成核验
                  </button>
                  <template v-if="file.referenceId">
                    <button type="button" :disabled="busy" @click="prepareRead(file.fileId)">
                      签名读取
                    </button>
                    <button type="button" :disabled="busy" @click="release(file)">释放引用</button>
                  </template>
                  <template v-if="file.referenceId && signed?.fileId === file.fileId">
                    <a :href="signed.url" target="_blank" rel="noopener noreferrer">打开文件</a>
                    <time :datetime="signed.expiresAt"
                      >{{ new Date(signed.expiresAt).toLocaleTimeString() }} 到期</time
                    >
                  </template>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else-if="files">暂无文件</p>
    </section>
  </main>
</template>

<style scoped>
form,
.file-field {
  display: grid;
  gap: 0.75rem;
}
fieldset {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  min-inline-size: 0;
  margin: 0;
  padding: 0;
  border: 0;
}
input {
  max-inline-size: 100%;
}
fieldset label {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  min-block-size: 3rem;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.file-list {
  margin-block-start: 1rem;
}
.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-block-end: 0.75rem;
}
.list-header h2 {
  margin: 0;
}
.table-scroll {
  overflow: auto;
  max-block-size: 32rem;
}
table {
  inline-size: 100%;
  border-spacing: 0;
  text-align: start;
}
th,
td {
  padding: 0.5rem;
  border-block-end: 1px solid #d2dfdb;
  text-align: start;
  white-space: nowrap;
}
th {
  background: #fff;
}
thead {
  position: sticky;
  inset-block-start: 0;
  z-index: 2;
}
tbody th {
  position: sticky;
  inset-inline-start: 0;
  z-index: 1;
}
.actions {
  align-items: center;
}
[role="alert"] {
  color: #8b2525;
}
</style>
