import { computed, ref } from 'vue'
import { LANGUAGES, TRANSLATIONS } from '@frontend/locales'

const FALLBACK_LOCALE = TRANSLATIONS.en ? 'en' : 'ro'

function toLocaleCode(value) {
    return value?.split(/[-_]/)[0]?.toLowerCase()
}

function getSavedLocale() {
    try {
        return toLocaleCode(localStorage.getItem('lang'))
    } catch {
        return null
    }
}

function getBrowserLocale() {
    const langRaw =
        navigator.languages?.[0] ||
        navigator.language ||
        Intl.DateTimeFormat().resolvedOptions().locale ||
        'en-US'

    return toLocaleCode(langRaw)
}

function resolveInitialLocale() {
    const saved = getSavedLocale()
    if (saved && TRANSLATIONS[saved]) return saved

    const browserLocale = getBrowserLocale()
    if (browserLocale && TRANSLATIONS[browserLocale]) return browserLocale

    return FALLBACK_LOCALE
}

const lang = ref(resolveInitialLocale())
document.documentElement.lang = lang.value

export function useT() {
    const currentLanguage = computed(() => {
        return LANGUAGES.find((item) => item.code === lang.value) || LANGUAGES[0]
    })

    function setLang(next) {
        if (!TRANSLATIONS[next]) return

        lang.value = next
        document.documentElement.lang = next

        try {
            localStorage.setItem('lang', next)
        } catch { }
    }

    function t(key) {
        const dict = TRANSLATIONS[lang.value] || TRANSLATIONS.ro
        return dict[key] ?? TRANSLATIONS.en?.[key] ?? TRANSLATIONS.ro[key] ?? key
    }

    return {
        lang,
        currentLanguage,
        setLang,
        t,
    }
}
