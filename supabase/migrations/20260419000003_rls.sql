-- 20260419000003_rls.sql
-- RLS policies for tenancy + reference tables.

-- organisations: members can see their own org; internal can see all
create policy "orgs: own or internal"
on organisations for select
using (
  id = (select organisation_id from app.current_membership())
  or (select org_status from app.current_membership()) = 'internal'
);

-- memberships: each user can see only their own row; internal can see all
create policy "memberships: own or internal"
on memberships for select
using (
  user_id = auth.uid()
  or (select org_status from app.current_membership()) = 'internal'
);

-- reference data: any authenticated user can read
create policy "countries: authenticated read"
on countries for select
to authenticated
using (true);

create policy "country_segments: authenticated read"
on country_segments for select
to authenticated
using (true);

create policy "variables: authenticated read"
on variables for select
to authenticated
using (true);

-- Writes to reference tables restricted to service_role (backend-only seeding and future migrations).
-- No INSERT/UPDATE/DELETE policies for authenticated users → RLS blocks them by default.
