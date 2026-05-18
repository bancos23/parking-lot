<script setup>
import LangSwitcher from '@frontend/components/LangSwitcher.vue'
import { useT } from '@frontend/composables/i18n'

const { t } = useT()

defineProps({
  eyebrow: { type: String, required: true },
  title: { type: String, required: true },
  description: { type: String, required: true },
  updated: { type: String, required: true },
  sections: { type: Array, required: true },
})
</script>

<template>
  <div class="legal-page">
    <header class="legal-topbar">
      <RouterLink class="legal-brand" :to="{ name: 'login' }" aria-label="Parking App">
        <span class="brand-mark">P</span>
        <span>
          <strong>Parking App</strong>
          <small>{{ t('brand.sub') }}</small>
        </span>
      </RouterLink>

      <nav class="legal-nav" :aria-label="t('legal.nav.label')">
        <RouterLink :to="{ name: 'terms' }">{{ t('auth.foot.terms') }}</RouterLink>
        <RouterLink :to="{ name: 'privacy' }">{{ t('auth.foot.privacy') }}</RouterLink>
        <RouterLink :to="{ name: 'support' }">{{ t('auth.foot.support') }}</RouterLink>
      </nav>

      <LangSwitcher />
    </header>

    <main class="legal-shell">
      <section class="legal-main">
        <div class="legal-hero">
          <div class="legal-eyebrow">{{ eyebrow }}</div>
          <h1>{{ title }}</h1>
          <p>{{ description }}</p>
        </div>

        <article class="legal-content">
          <section v-for="section in sections" :key="section.title" class="legal-section">
            <h2>{{ section.title }}</h2>
            <p v-for="paragraph in section.paragraphs" :key="paragraph">{{ paragraph }}</p>
            <ul v-if="section.items?.length">
              <li v-for="item in section.items" :key="item">{{ item }}</li>
            </ul>
          </section>
        </article>
      </section>

      <aside class="legal-aside" :aria-label="t('legal.summary.label')">
        <div class="legal-summary">
          <div class="legal-summary-label">{{ t('legal.summary.updated') }}</div>
          <div class="legal-summary-value">{{ updated }}</div>
        </div>

        <div class="legal-summary">
          <div class="legal-summary-label">{{ t('legal.summary.owner') }}</div>
          <div class="legal-summary-value">{{ t('legal.summary.owner.value') }}</div>
        </div>

        <RouterLink class="btn btn-primary legal-cta" :to="{ name: 'login' }">{{ t('legal.back') }}</RouterLink>
      </aside>
    </main>
  </div>
</template>
