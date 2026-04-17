# CulinaraOs — Lovable Build Prompt

## IMPORTANT: Upload these screenshots alongside this prompt
Take screenshots from culinaraos.com of: Login, Restaurant Selector, Dashboard, Food Cost table, Menu Analysis, Invoices, Settings, Arthur's empty dashboard. Tell Lovable: "Match these screens exactly."

---

## What to build
A multi-restaurant SaaS food cost intelligence platform called **CulinaraOs**. Dark mode only. Three screens: Login → Restaurant Selector → Main App. Match the screenshots exactly.

---

## Design System — copy these values exactly

```
Font: Inter (Google Fonts)
Page background:       #171B26
Card background:       #1F2433
Sidebar background:    #111520
Login/selector bg:     radial-gradient(ellipse at 30% 20%, #1C2340 0%, #0F1320 100%)
Border color:          rgba(255,255,255,0.07)
Muted text:            #8B92A5
Body text:             #E2E8F0

Accent blue:           #4F8EF7
Green:                 #34C97A
Red:                   #F05252
Amber:                 #F5A623
Purple:                #A78BFA

Active nav item bg:    rgba(79,142,247,0.14)
Active nav text:       #4F8EF7
Nav hover:             rgba(255,255,255,0.05)

Card border-radius:    14px
Button border-radius:  10px
Sidebar width:         128px
```

---

## Screen 1 — Login

- Full screen dark radial gradient background (navy → near black)
- Top-left: "CulinaraOs" wordmark. Top-right: "Restaurant Intelligence Platform" muted text
- Center card (max-width 420px): frosted glass effect, rounded 22px
  - "Welcome back" heading
  - "Sign in to your restaurant intelligence dashboard" subtitle
  - Email input field
  - Password input field
  - "Sign in →" blue button (full width)
  - Below button: "Sign in with your CulinaraOs account" muted small text
- Below card: "Trusted by 12+ restaurants in Quebec"
- Supabase auth — real email/password login

---

## Screen 2 — Restaurant Selector

- Same dark gradient background as login
- Top bar: "CulinaraOs" left, user avatar (initials circle, blue) + name + "PRO" badge right
- "Good morning, [Name] 👋" large greeting
- "Select a restaurant to open its dashboard" subtitle (muted)
- Restaurant cards (full width, dark card with subtle border):
  - **Bottē Restaurant** — "● Live" green badge, location "Hudson, Quebec · Artisanal Sourdough Pizza", shows Food Cost % (red: 39.1%), Period Revenue (green: $36,570), Target (25.0%), "3 alerts" amber badge, "Synced 5 min ago"
  - **Arthur's Nosh Bar** — "⏳ Setting up" amber badge, location "Saint-Henri, Montréal, QC", onboarding progress bar at 15%, "Not connected" muted
  - **+ Add Restaurant** — dashed border card, muted text

---

## Screen 3 — Main App Layout

### Sidebar (128px wide, #111520)
- Top: "CulinaraOs" logo text + "PRO" purple badge
- Restaurant switcher: restaurant name + location, small dropdown arrow
- Nav sections with labels:

**VUE D'ENSEMBLE**
- Aperçus IA (AI badge, purple)
- Assistant IA
- Tableau de bord (Dashboard) ← default active
- Bilan de la semaine

**ANALYSE**
- Coût matière (Food Cost)
- Analyse du menu (Menu Analysis)
- Performance

**OPÉRATIONS**
- Prep & Recettes
- Tableau de prep (LIVE badge, green)
- Contrôle des portions (Yield)
- Inventaire
- Guide de commande (Order Guide)
- Équipe & tâches (Staff)

**FINANCES**
- Factures (Invoices)
- Rapports (Reports)
- Médias sociaux (Social)

**Bottom of sidebar:**
- "● Sync en direct" green dot + text
- Language toggle: EN / FR
- User avatar (blue circle "TG") + "Thomas Gevas" + "thomas@culinaraos.com"

### Top bar (content area)
- Section title left, restaurant name + date range center, "Sync Now" blue button right

---

## The 14 Sections

### 1. Dashboard (Tableau de bord)
- Savings banner: dark blue card "VOTRE OPPORTUNITÉ CETTE PÉRIODE — If you hit the 25% food cost target, you keep an extra $5,156" with 3 priority action chips
- Alert strip: 3 colored alert pills (red food cost, amber POS gap, orange GF upgrade)
- 4 KPI cards in a grid:
  - Food Cost %: 39.1% (red), progress bar 0–50%, "14.1pp over target"
  - Behind Target: $5,156 (red), "$104/day"
  - Period Revenue: $36,570 (green), "1,895 units · ~38.7 covers/day"
  - Gross Profit: $21,150, "Before labour & overhead"
- 7-week trend chart (line chart, dark grid, blue line)
- Secondary KPI cards: Beverage FC 20.4%, Beverage Rate 33.7%, Prime Cost 71.5%

### 2. Food Cost (Coût matière)
- Subtitle: "Bottē Restaurant · Jan 25 – Mar 15, 2026"
- Filter tabs: All items / Pizza Rossa / Pizza Bianca / Very Veggie / Salads / Sandwiches / Other / 🍺 Beverages
- Table columns: ARTICLE | CATEGORY (colored pill) | UNITS | PRICE | PORTION COST | FOOD COST % | REVENUE | GM/UNIT | GROSS MARGIN | STATUS
- Status badges: ⭐ Star (green), 💎 Hidden Gem (blue), 🐴 Workhorse (amber), ⚠ Underperformer (red)
- 23 rows of data
- "+ Add Item" floating blue button bottom right

### 3. Menu Analysis (Analyse du menu)
- 4 sections: ⭐ Stars (High Volume · High Margin), 🧩 Puzzles (Low Volume · High Margin), 🐴 Plowhorses (High Volume · Low Margin), 🐕 Dogs (Low Volume · Low Margin)
- Each section: colored header, item list with units + price

### 4. Insights (Aperçus IA)
- "$3,064 recoverable value" banner (dark blue)
- 5 AI insight cards, each with: category tag, insight title, finding text, recommended action, impact amount

### 5. Weekly Snapshot (Bilan de la semaine)
- Week KPIs, top items table, on-track status, upcoming orders, action checklist

### 6. Efficiency (Performance)
- Three score gauges: Pricing 68/100, Prep 74/100, Sourcing 44/100
- Supplier price tracker table
- Food safety checklist

### 7. Prep & Recipes
- Weekly prep quantities by category
- Recipe cards

### 8. Prep Board (Tableau de prep) — LIVE badge
- Kanban: To Prep / In Progress / Done columns
- Each card: item name, quantity, time estimate
- "Kitchen Mode" button for full-screen iPad view

### 9. Yield Control (Contrôle des portions)
- Pack → Portion → Yield table (12 ingredients)
- "Tonight's Pull Calculator": enter covers → get bags to pull
- Daily variance tip

### 10. Order Guide (Guide de commande)
- 5 suppliers (Gordon Food Service, Les Jardins QS, Farinex, Costco Wholesale, Les Serres Sagami)
- Each with ingredient list, par levels, order quantities

### 11. Staff & Tasks (Équipe & tâches)
- Today's shift: 4 staff cards with name, role, hours, labor cost
- Daily task board with categories

### 12. Invoices (Factures)
- Inbox email: botte@culinaraos.com (shown as blue link)
- Status chips: "3 need review" (amber) / "2 pending" (blue) / "22 processed" (green)
- Invoice list: each row has invoice# (blue link), supplier name, items summary, amount, status badge (À réviser / Validé QBO)
- Right panel: "How invoices flow" 4-step explanation + "This period" summary card
- "+ Upload Invoice" button top right

### 13. Reports (Rapports)
- Period summary card: restaurant name, date range, total revenue
- 5 report type cards
- Quick export buttons (PDF, CSV)

### 14. Settings (Paramètres)
- Integration cards in 2-column grid:
  - Lightspeed Restaurant: ● Connected (green), account details, sync controls
  - QuickBooks Online: connected/not connected
  - Invoice email forwarding
  - Planifico (staff)
  - Piecemeal (inventory)

---

## Arthur's Empty States
When Arthur's Nosh Bar is selected, every section shows a clean placeholder instead of Bottē data:
- Dashboard: 4 KPI cards all show "—" and "No data yet", no charts, "Dashboard ready — waiting for data" message with invoice email
- Food Cost: Arthur's menu items (estimated FCs, no real sales data)
- Efficiency: "Connect Cluster POS to unlock scores"
- Staff: "No staff data yet — connect Planifico"
- Invoices: arthurs@culinaraos.com, "No invoices received yet"
- Inventory: "No inventory data yet — connect Piecemeal"
- Reports: "No report data yet"
- Settings: Cluster POS (not connected), QuickBooks (not connected), Planifico (not connected), Piecemeal (not connected)

---

## Tech Stack
- Next.js 14 + TypeScript + Tailwind CSS
- Supabase auth (email/password) + Supabase database
- Row-level security: each restaurant sees only its own data
- Admin role sees all restaurants
- Recharts for all charts (dark theme, no white backgrounds)
- Vercel deployment
- All API keys in environment variables

---

## Demo Credentials to pre-populate
- admin: demo@culinaraos.com / demo1234 (sees both restaurants)
- botte owner: botte@culinaraos.com / botte2024
- arthurs owner: arthurs@culinaraos.com / arthurs2024
