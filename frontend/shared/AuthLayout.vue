<script setup lang="ts">
import BrandMark from "./BrandMark.vue";

defineProps<{
  flat?: boolean;
  brand: string;
  introTitle: string;
  introDescription: string;
  introFeatures: readonly { title: string; description: string }[];
  title: string;
  description: string;
}>();
</script>

<template>
  <div class="auth-layout" :class="{ 'auth-layout--flat': flat }">
    <div class="auth-layout__intro">
      <article class="auth-layout__intro-content">
        <header class="auth-layout__intro-heading">
          <p class="auth-layout__brand">
            <BrandMark />
            {{ brand }}
          </p>
          <p class="auth-layout__headline">{{ introTitle }}</p>
        </header>
        <p class="auth-layout__description">{{ introDescription }}</p>
        <dl class="auth-layout__features">
          <div v-for="feature in introFeatures" :key="feature.title">
            <dt>{{ feature.title }}</dt>
            <dd>{{ feature.description }}</dd>
          </div>
        </dl>
      </article>
    </div>
    <div class="auth-layout__form-side">
      <section class="auth-layout__form-content">
        <header class="auth-layout__heading">
          <h1>{{ title }}</h1>
          <p class="muted">{{ description }}</p>
        </header>
        <slot />
        <div v-if="$slots.footer" class="auth-layout__footer">
          <slot name="footer" />
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.auth-layout {
  --auth-card-shadow: 0 1rem 2.5rem rgb(31 77 56 / 9%);
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
}

.auth-layout__intro {
  display: none;
}

.auth-layout__form-side {
  display: grid;
  place-items: center;
  padding: clamp(1rem, 4vw, 3rem);
}

.auth-layout__form-content {
  inline-size: min(100%, 27rem);
}

.auth-layout:not(.auth-layout--flat) .auth-layout__form-content {
  padding: clamp(1.25rem, 4vw, 2rem);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--auth-card-shadow);
}

.auth-layout--flat {
  background: var(--panel);
}

.auth-layout--flat .auth-layout__form-side {
  padding: clamp(1.25rem, 6vw, 5rem);
}

.auth-layout__heading {
  display: grid;
  gap: var(--space-2);
  margin-block-end: var(--space-4);
}

.auth-layout__heading h1 {
  font-size: 1.75rem;
}

.auth-layout--flat .auth-layout__heading h1 {
  font-size: clamp(1.75rem, 1.25rem + 1vw, 2.25rem);
}

.auth-layout--flat .auth-layout__heading {
  margin-block-end: var(--space-5);
}

.auth-layout--flat .auth-layout__heading .muted {
  color: var(--ink-soft);
}

:slotted(.auth-form) {
  display: grid;
  gap: var(--space-3);
}

.auth-layout--flat :slotted(.auth-form) {
  gap: var(--space-4);
}

.auth-layout__footer {
  margin-block-start: var(--space-5);
  padding-block-start: var(--space-4);
  border-block-start: 1px solid var(--line);
  color: var(--ink-soft);
  font-size: 0.875rem;
}

.auth-layout__footer :deep(a) {
  font-weight: 650;
}

@media (width >= 48rem) {
  .auth-layout {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .auth-layout__intro {
    display: grid;
    place-items: center;
    padding: clamp(2rem, 6vw, 6rem);
    color: var(--auth-ink);
    background: var(--auth-intro);
  }

  .auth-layout__intro-content {
    display: grid;
    gap: var(--space-4);
    inline-size: min(100%, 31rem);
  }

  .auth-layout:not(.auth-layout--flat) .auth-layout__intro-content {
    padding: clamp(1.25rem, 3vw, 2.5rem);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: linear-gradient(145deg, var(--panel), var(--brand-soft));
    box-shadow: var(--auth-card-shadow);
  }

  .auth-layout--flat .auth-layout__intro-content {
    gap: var(--space-5);
  }

  .auth-layout__intro-heading {
    display: grid;
    gap: var(--space-4);
  }

  .auth-layout__brand {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-weight: 650;
  }

  .auth-layout__headline {
    font-size: clamp(1.875rem, 3.2vw, 3.25rem);
    font-weight: 700;
    line-height: 1.15;
    text-wrap: balance;
  }

  .auth-layout--flat .auth-layout__headline {
    font-size: clamp(1.875rem, 1rem + 2.8vw, 3.5rem);
  }

  .auth-layout__description {
    max-inline-size: 25rem;
    color: var(--ink-soft);
    font-size: 1rem;
  }

  .auth-layout__features {
    display: grid;
    gap: var(--space-3);
    margin: 0;
  }

  .auth-layout__features > div {
    display: grid;
    gap: 0.125rem;
    padding-block-start: var(--space-3);
    border-block-start: 1px solid var(--line);
  }

  .auth-layout--flat .auth-layout__features > div {
    padding-block-start: var(--space-4);
    border-color: rgb(37 75 60 / 20%);
  }

  .auth-layout__features dt {
    font-weight: 650;
  }

  .auth-layout__features dd {
    margin: 0;
    color: var(--ink-soft);
    font-size: 0.875rem;
  }
}
</style>
