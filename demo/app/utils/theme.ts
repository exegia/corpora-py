import { defineTheme } from "@astryxdesign/core/theme"

export const CorporaTheme = defineTheme({
  name: "Corpora",
  tokens: {
    "--color-accent": "light-dark(#BD9D00, #F9C301)",
    "--color-accent-muted": "light-dark(#BD9D0033, #F9C30140)",
    "--color-on-accent": "light-dark(#FFFFFF, #F9C301)",
    "--color-neutral": "light-dark(#BD9D001A, #F4F3F133)",
    "--color-background-surface": "light-dark(#FFFFFF, #0D0D0D)",
    "--color-background-body": "light-dark(#F5F5F5, #1C1C1C)",
    "--color-overlay": "light-dark(#BD9D0066, #1D1B1699)",
    "--color-overlay-hover": "light-dark(#BD9D000D, #FFFFFF0D)",
    "--color-overlay-pressed": "light-dark(#BD9D001A, #FFFFFF1A)",
    "--color-background-muted": "light-dark(#1D1D160D, #1D1B1680)",
    "--color-text-primary": "light-dark(#121212, #E6E2DB)",
    "--color-text-secondary": "light-dark(#404040, #AEA99E)",
    "--color-text-disabled": "light-dark(#7D7D7D, #605E52)",
    "--color-text-accent": "light-dark(#BD9D00, #DBBD6B)",
    "--color-on-dark": "#ffffff",
    "--color-on-light": "#171717",
    "--color-icon-accent": "light-dark(#006F3F, #6CDBA4)",
    "--color-icon-primary": "light-dark(#BD9D00, #E6E4DB)",
    "--color-icon-secondary": "light-dark(#151514, #AEA99E)",
    "--color-icon-disabled": "light-dark(#949384, #605E52)",
    "--color-background-card": "light-dark(#FFFFFF, #141414)",
    "--color-background-popover": "light-dark(#F5F5F5, #32312A)",
    "--color-background-inverted": "light-dark(#161D19, #F4FFF8)",
    "--color-success": "light-dark(#007004, #9fe59b)",
    "--color-success-muted": "light-dark(#c5e5c0, #84c9803D)",
    "--color-on-success": "light-dark(#ffffff, #171717)",
    "--color-error": "light-dark(#a50c25, #ffc6c1)",
    "--color-error-muted": "light-dark(#facecb, #ff9e973D)",
    "--color-on-error": "light-dark(#ffffff, #171717)",
    "--color-warning": "light-dark(#745b00, #fdcf4f)",
    "--color-warning-muted": "light-dark(#f8da9d, #deb4333D)",
    "--color-on-warning": "#171717",
    "--color-border": "light-dark(#8080801A, #0000001A)",
    "--color-border-emphasized": "light-dark(#DEDEDE, #000000)",
    "--color-skeleton": "light-dark(#D9D9D9, #121211)",
    "--color-track": "light-dark(#9FAFA5, #3C4A42)",
    "--color-shadow": "light-dark(#0000001A, #0A0A0A4D)",
    "--color-background-blue": "light-dark(#c4ddfb, #9eb7ff3D)",
    "--color-border-blue": "light-dark(#b1c9e7, #6d9cfe)",
    "--color-icon-blue": "light-dark(#00458c, #9eb7ff)",
    "--color-text-blue": "light-dark(#00458c, #c7d3ff)",
    "--color-background-cyan": "light-dark(#a3e0ef, #83c2d43D)",
    "--color-border-cyan": "light-dark(#91d3e3, #67a7b8)",
    "--color-icon-cyan": "light-dark(#00505f, #83c2d4)",
    "--color-text-cyan": "light-dark(#00505f, #9edef0)",
    "--color-background-gray": "light-dark(#e5e5e5, var(--color-neutral))",
    "--color-border-gray": "light-dark(#d4d4d4, #262626)",
    "--color-icon-gray": "light-dark(#525252, #a3a3a3)",
    "--color-text-gray": "light-dark(#262626, #e5e5e5)",
    "--color-background-green": "light-dark(#c5e5c0, #84c9803D)",
    "--color-border-green": "light-dark(#b2d1ac, #69ad67)",
    "--color-icon-green": "light-dark(#0c5700, #84c980)",
    "--color-text-green": "light-dark(#0c5700, #9fe59b)",
    "--color-background-orange": "light-dark(#fad0b5, #ffa2583D)",
    "--color-border-orange": "light-dark(#e6bda2, #e2883e)",
    "--color-icon-orange": "light-dark(#6e3500, #ffa258)",
    "--color-text-orange": "light-dark(#6e3500, #ffc9a2)",
    "--color-background-pink": "light-dark(#fccadc, #ff99c33D)",
    "--color-border-pink": "light-dark(#e7b7c8, #f273aa)",
    "--color-icon-pink": "light-dark(#83004b, #ff99c3)",
    "--color-text-pink": "light-dark(#83004b, #ffc3da)",
    "--color-background-purple": "light-dark(#eccef3, #f297ff3D)",
    "--color-border-purple": "light-dark(#d8bbdf, #dd74f0)",
    "--color-icon-purple": "light-dark(#700084, #f297ff)",
    "--color-text-purple": "light-dark(#700084, #fac1ff)",
    "--color-background-red": "light-dark(#facecb, #ff9e973D)",
    "--color-border-red": "light-dark(#e6bab8, #ff6f6c)",
    "--color-icon-red": "light-dark(#89001a, #ff9e97)",
    "--color-text-red": "light-dark(#89001a, #ffc6c1)",
    "--color-background-teal": "light-dark(#a5e3d6, #7ec6b83D)",
    "--color-border-teal": "light-dark(#94d6c8, #63ab9d)",
    "--color-icon-teal": "light-dark(#005348, #7ec6b8)",
    "--color-text-teal": "light-dark(#005348, #99e2d3)",
    "--color-background-yellow": "light-dark(#f8da9d, #deb4333D)",
    "--color-border-yellow": "light-dark(#e4c279, #c0990e)",
    "--color-icon-yellow": "light-dark(#584400, #deb433)",
    "--color-text-yellow": "light-dark(#584400, #fdcf4f)",
    "--font-family-body": "\"Poppins\", -apple-system, sans-serif",
    "--font-family-code": "ui-monospace, \"SF Mono\", Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace",
    "--font-family-heading": "Georgia, \"Times New Roman\", serif",
    "--font-size-4xs": "0.3125rem",
    "--font-size-3xs": "0.375rem",
    "--font-size-2xs": "0.4375rem",
    "--font-size-xs": "0.5rem",
    "--font-size-sm": "0.625rem",
    "--font-size-base": "0.75rem",
    "--font-size-lg": "0.875rem",
    "--font-size-xl": "1.0625rem",
    "--font-size-2xl": "1.3125rem",
    "--font-size-3xl": "1.5625rem",
    "--font-size-4xl": "1.875rem",
    "--font-size-5xl": "2.25rem",
    "--text-heading-2-leading": "1.4118",
    "--text-heading-3-leading": "1.4286",
    "--text-heading-4-leading": "1.6667",
    "--text-heading-5-leading": "1.6",
    "--text-heading-6-leading": "1.5",
    "--text-body-leading": "1.6667",
    "--text-large-leading": "1.4286",
    "--text-label-leading": "1.6667",
    "--text-code-leading": "1.6667",
    "--text-supporting-leading": "1.6",
    "--text-display-1-leading": "1.2222",
    "--text-display-2-leading": "1.4667",
    "--text-display-3-leading": "1.44",
    "--size-element-sm": "24px",
    "--size-element-md": "28px",
    "--size-element-lg": "32px",
    "--shadow-low": "0 2px 4px light-dark(oklch(0 0 0 / 5%), oklch(0 0 0 / 25%)), 0 4px 8px light-dark(oklch(0 0 0 / 10%), oklch(0 0 0 / 40%)), inset 0 0 0 1px light-dark(transparent, oklch(1 0 0 / 8%))",
    "--shadow-med": "0 2px 4px light-dark(oklch(0 0 0 / 5%), oklch(0 0 0 / 35%)), 0 4px 12px light-dark(oklch(0 0 0 / 10%), oklch(0 0 0 / 50%)), inset 0 0 0 1px light-dark(transparent, oklch(1 0 0 / 12%))",
    "--shadow-high": "0 4px 6px light-dark(oklch(0 0 0 / 10%), oklch(0 0 0 / 50%)), 0 12px 24px light-dark(oklch(0 0 0 / 15%), oklch(0 0 0 / 70%)), inset 0 0 0 1px light-dark(transparent, oklch(1 0 0 / 15%))",
    "--shadow-inset-hover": "inset 0px 0px 0px 2px rgba(38, 38, 38, 0.3)",
    "--shadow-inset-selected": "inset 0px 0px 0px 2px rgba(38, 38, 38, 0.5)",
    "--shadow-inset-success": "inset 0px 0px 0px 2px #1981004D",
    "--shadow-inset-warning": "inset 0px 0px 0px 2px #ffce2f4D",
    "--shadow-inset-error": "inset 0px 0px 0px 2px #e33f4a4D",
    "--duration-fast-min": "95ms",
    "--duration-fast": "125ms",
    "--duration-fast-max": "165ms",
    "--duration-medium-min": "225ms",
    "--duration-medium": "300ms",
    "--duration-medium-max": "400ms",
    "--duration-slow-min": "525ms",
    "--duration-slow": "700ms",
    "--duration-slow-max": "935ms",
    "--color-syntax-keyword": "light-dark(#700084, #efa8ff)",
    "--color-syntax-string": "light-dark(#005600, #a6d2a2)",
    "--color-syntax-comment": "light-dark(#737373, #a3a3a3)",
    "--color-syntax-number": "light-dark(#6e3500, #ffb37f)",
    "--color-syntax-function": "light-dark(#00458c, #a0caff)",
    "--color-syntax-type": "light-dark(#700084, #efa8ff)",
    "--color-syntax-variable": "light-dark(#171717, #e5e5e5)",
    "--color-syntax-operator": "light-dark(#737373, #a3a3a3)",
    "--color-syntax-constant": "light-dark(#6e3500, #ffb37f)",
    "--color-syntax-tag": "light-dark(#89001a, #ffaeaa)",
    "--color-syntax-attribute": "light-dark(#584400, #eec12f)",
    "--color-syntax-property": "light-dark(#005348, #83dac9)",
    "--color-syntax-punctuation": "light-dark(#a3a3a3, #525252)",
    "--color-syntax-background": "light-dark(#fafafa, #0a0a0a)"
  },
  components: {
    "heading": {
      "level:1": {
        "fontFamily": "var(--font-family-heading)",
        "fontSize": "var(--text-heading-1-size)",
        "fontWeight": "var(--text-heading-1-weight)",
        "lineHeight": "var(--text-heading-1-leading)"
      },
      "level:2": {
        "fontFamily": "var(--font-family-heading)",
        "fontSize": "var(--text-heading-2-size)",
        "fontWeight": "var(--text-heading-2-weight)",
        "lineHeight": "var(--text-heading-2-leading)"
      },
      "level:3": {
        "fontFamily": "var(--font-family-heading)",
        "fontSize": "var(--text-heading-3-size)",
        "fontWeight": "var(--text-heading-3-weight)",
        "lineHeight": "var(--text-heading-3-leading)"
      },
      "level:4": {
        "fontFamily": "var(--font-family-heading)",
        "fontSize": "var(--text-heading-4-size)",
        "fontWeight": "var(--text-heading-4-weight)",
        "lineHeight": "var(--text-heading-4-leading)"
      },
      "level:5": {
        "fontFamily": "var(--font-family-heading)",
        "fontSize": "var(--text-heading-5-size)",
        "fontWeight": "var(--text-heading-5-weight)",
        "lineHeight": "var(--text-heading-5-leading)"
      },
      "level:6": {
        "fontFamily": "var(--font-family-heading)",
        "fontSize": "var(--text-heading-6-size)",
        "fontWeight": "var(--text-heading-6-weight)",
        "lineHeight": "var(--text-heading-6-leading)"
      }
    },
    "text": {
      "type:body": {
        "fontFamily": "var(--font-family-body)",
        "fontSize": "var(--text-body-size)",
        "lineHeight": "var(--text-body-leading)"
      },
      "type:large": {
        "fontFamily": "var(--font-family-body)",
        "fontSize": "var(--text-large-size)",
        "lineHeight": "var(--text-large-leading)"
      },
      "type:label": {
        "fontFamily": "var(--font-family-body)",
        "fontSize": "var(--text-label-size)",
        "lineHeight": "var(--text-label-leading)"
      },
      "type:code": {
        "fontFamily": "var(--font-family-code)",
        "fontSize": "var(--text-code-size)",
        "lineHeight": "var(--text-code-leading)"
      },
      "type:supporting": {
        "fontFamily": "var(--font-family-body)",
        "fontSize": "var(--text-supporting-size)",
        "lineHeight": "var(--text-supporting-leading)"
      },
      "type:display-1": {
        "fontFamily": "var(--font-family-heading)",
        "fontSize": "var(--text-display-1-size)",
        "lineHeight": "var(--text-display-1-leading)"
      },
      "type:display-2": {
        "fontFamily": "var(--font-family-heading)",
        "fontSize": "var(--text-display-2-size)",
        "lineHeight": "var(--text-display-2-leading)"
      },
      "type:display-3": {
        "fontFamily": "var(--font-family-heading)",
        "fontSize": "var(--text-display-3-size)",
        "lineHeight": "var(--text-display-3-leading)"
      }
    },
    "button": {
      "variant:destructive": {
        "backgroundColor": "var(--color-error-muted)",
        "color": "var(--color-error)"
      }
    },
    "badge": {
      "variant:info": {
        "backgroundColor": "light-dark(#0074e2, #6d9cfe)",
        "color": "light-dark(#ffffff, #171717)"
      },
      "variant:neutral": {
        "backgroundColor": "var(--color-background-gray)",
        "color": "var(--color-text-gray)"
      },
      "variant:success": {
        "backgroundColor": "light-dark(#198100, #64af4c)",
        "color": "light-dark(#ffffff, #171717)"
      },
      "variant:warning": {
        "backgroundColor": "#ffce2f",
        "color": "#171717"
      },
      "variant:error": {
        "backgroundColor": "light-dark(#e33f4a, #ff705d)",
        "color": "light-dark(#ffffff, #171717)"
      },
      "variant:red": {
        "backgroundColor": "var(--color-background-red)",
        "color": "var(--color-text-red)"
      },
      "variant:orange": {
        "backgroundColor": "var(--color-background-orange)",
        "color": "var(--color-text-orange)"
      },
      "variant:yellow": {
        "backgroundColor": "var(--color-background-yellow)",
        "color": "var(--color-text-yellow)"
      },
      "variant:green": {
        "backgroundColor": "var(--color-background-green)",
        "color": "var(--color-text-green)"
      },
      "variant:teal": {
        "backgroundColor": "var(--color-background-teal)",
        "color": "var(--color-text-teal)"
      },
      "variant:cyan": {
        "backgroundColor": "var(--color-background-cyan)",
        "color": "var(--color-text-cyan)"
      },
      "variant:blue": {
        "backgroundColor": "var(--color-background-blue)",
        "color": "var(--color-text-blue)"
      },
      "variant:purple": {
        "backgroundColor": "var(--color-background-purple)",
        "color": "var(--color-text-purple)"
      },
      "variant:pink": {
        "backgroundColor": "var(--color-background-pink)",
        "color": "var(--color-text-pink)"
      },
      "variant:gray": {
        "backgroundColor": "var(--color-background-gray)",
        "color": "var(--color-text-gray)"
      }
    },
    "banner": {
      "status:info": {
        "backgroundColor": "var(--color-background-blue)",
        "--color-accent-muted": "transparent",
        "--color-text-primary": "var(--color-text-blue)",
        "--color-text-secondary": "var(--color-text-blue)",
        "--color-accent": "var(--color-text-blue)"
      },
      "status:success": {
        "--color-text-primary": "var(--color-text-green)",
        "--color-text-secondary": "var(--color-text-green)",
        "--color-success": "var(--color-text-green)"
      },
      "status:warning": {
        "--color-text-primary": "var(--color-text-yellow)",
        "--color-text-secondary": "var(--color-text-yellow)",
        "--color-warning": "var(--color-text-yellow)"
      },
      "status:error": {
        "--color-text-primary": "var(--color-text-red)",
        "--color-text-secondary": "var(--color-text-red)",
        "--color-error": "var(--color-text-red)"
      }
    },
    "switch": {
      "base": {
        "--color-background-gray": "var(--color-border-emphasized)"
      }
    },
    "progressbar": {
      "base": {
        "--color-background-muted": "var(--color-border-emphasized)"
      },
      "variant:accent": {
        "--color-accent": "#0074e2"
      },
      "variant:success": {
        "--color-success": "#198100"
      },
      "variant:warning": {
        "--color-warning": "#ffce2f"
      },
      "variant:error": {
        "--color-error": "#e33f4a"
      }
    },
    "card": {
      "base": {
        "padding": "var(--spacing-3)"
      }
    },
    "section": {
      "base": {
        "padding": "var(--spacing-3)"
      }
    }
  }
})
