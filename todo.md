# Warehouse Job Display - TODO

## Phase 1: Database & API Integration
- [x] Create database schema for areas, job mappings, and display settings
- [x] Implement Current-RMS API integration helper
- [x] Create tRPC procedures for fetching jobs from Current-RMS
- [x] Add error handling and retry logic for API calls

## Phase 2: Configuration Interface
- [x] Build admin dashboard layout
- [x] Create area management (create, edit, delete areas)
- [x] Implement job selection interface (search and select from Current-RMS)
- [x] Build area-to-job mapping UI
- [x] Add display settings configuration (refresh rate, theme)

## Phase 3: Warehouse Display View
- [x] Create large-format display component
- [x] Redesign display layout - center content, improve formatting, remove status
- [x] Add job information cards (title, number, load date/time)
- [x] Build responsive design for various screen sizes
- [x] Add area name and status indicators
- [x] Fix: Display job title/name on warehouse screen - job titles now cached when added
- [x] Show job title in admin job search interface
- [x] Fix: Fetch and cache job details when adding job to area

## Phase 4: Real-time Features
- [x] Implement periodic data refresh (configurable intervals)
- [x] Add real-time job status updates

## Phase 5: Authentication Fix
- [x] Make warehouse display view public (no auth required)
- [x] Keep admin dashboard protected (auth required)
- [x] Fix OAuth redirect loop issue with ProtectedRoute wrapper
- [x] Create error states and fallback UI
- [x] Add loading indicators for display view

## Phase 6: Local Authentication System
- [x] Add admin users table to database schema
- [x] Create login/register endpoints
- [x] Build login page UI
- [x] Implement session-based auth (replace OAuth)
- [x] Keep warehouse display screens public

## Phase 5: Polish & Testing
- [x] Test Current-RMS API integration
- [x] Verify display readability at distance
- [x] Test configuration workflows
- [ ] Add keyboard shortcuts for display mode
- [ ] Create checkpoint

## Phase 6: Delivery
- [ ] Document setup and usage
- [ ] Provide deployment instructions
