# CHG-014 Maven 依赖缓存与限流

2026-11-26 确认采用本方案。工作流已在本地更新，待 GitHub Actions 验收。

## 现象与原因

[GitHub Actions 作业 139860952829](https://github.com/iy88/se-course-project-1/actions/runs/45805430494/job/139860952829) 的 Backend Integration 已恢复 Maven 依赖和 Wrapper 缓存。随后执行 `verify -Pintegration` 时，解析 `maven-failsafe-plugin:3.5.6` 的 POM，Maven Central 返回 HTTP 429，构建在运行集成测试前失败。同一运行的 Backend / Maven 恢复了同一个依赖缓存主键，执行普通 `verify` 成功。

[CI 工作流](../../../.github/workflows/ci.yml) 给两个作业配置了相同的 POM 哈希输入。普通 `verify` 与集成作业在独立 runner 上运行，后者激活 [integration profile](../../../backend/backend-app/pom.xml) 后还需要解析 Failsafe 及其依赖。普通作业生成的快照可能缺少这些构件。命中已有主键后，当次新下载的构件也不会回写该快照，因此后续 runner 仍可能请求相同文件。[setup-java 缓存说明](https://github.com/actions/setup-java/blob/d1374f8ac74474200d16ef8ecee22c7ae7a51880/docs/advanced-usage.md)

该日志证实了缓存命中后仍有远端解析和限流。缓存的初始写入者、同一构件的重复下载次数及限流触发来源待进一步核对。

## 工作流变更与验收

1. 为普通构建和集成构建分别维护 Maven 依赖缓存键，分别由实际执行 `verify` 和 `verify -Pintegration` 的成功作业填充。缓存键包含作业用途、版本前缀、runner 平台和 Maven 配置哈希。没有精确命中时，在 GitHub 允许访问的分支范围内按同一用途的前缀恢复最近快照，再补齐缺失构件。Wrapper 缓存继续按发行版配置共享，JDK 缓存继续由 setup-java 管理。
2. 在同一代码版本上检查冷、热两轮 CI。确认冷轮的两个作业均成功并写入各自缓存，热轮命中对应主键。对比 Maven Central 的下载请求数和 Failsafe 构件的解析来源，核对单元测试与 PostgreSQL／Redis 集成测试均实际执行。再以一次 POM 变更验证旧快照可回退恢复，缺失依赖可补齐并保存到新键。
3. 如果冷启动仍频繁遇到 429，再评估团队维护的 Maven 仓库代理，以复用跨作业和跨分支的上游下载。

已核对失败日志、工作流 YAML、缓存键隔离和 Wrapper 路径。`git diff --check` 通过。actionlint 在变更前后均报告相同的两条服务端口表达式类型问题。缓存写入、命中及 Maven Central 请求量仍待 GitHub Actions 验收。
