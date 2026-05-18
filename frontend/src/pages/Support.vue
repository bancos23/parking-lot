<script setup>
import { computed } from 'vue'
import LegalPageShell from '@frontend/components/LegalPageShell.vue'
import { useT } from '@frontend/composables/i18n'

const { t } = useT()

const sectionBlueprints = [
  { key: 'contact', paragraphs: 1, items: 3 },
  { key: 'include', paragraphs: 1, items: 4 },
  { key: 'response', paragraphs: 1, items: 3 },
  { key: 'self_service', paragraphs: 1 },
]

const sections = computed(() => sectionBlueprints.map(({ key, paragraphs, items = 0 }) => ({
  title: t(`legal.support.sections.${key}.title`),
  paragraphs: Array.from({ length: paragraphs }, (_, index) => t(`legal.support.sections.${key}.paragraphs.${index}`)),
  items: Array.from({ length: items }, (_, index) => t(`legal.support.sections.${key}.items.${index}`)),
})))
</script>

<template>
  <LegalPageShell
    :eyebrow="t('legal.support.eyebrow')"
    :title="t('legal.support.title')"
    :description="t('legal.support.description')"
    :updated="t('legal.updated')"
    :sections="sections"
  />
</template>
