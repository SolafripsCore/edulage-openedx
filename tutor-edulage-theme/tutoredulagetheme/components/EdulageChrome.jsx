/*
 * EduLage site chrome for Open edX MFEs.
 * Port of EduLage/src/components/Header.tsx and Footer.tsx (Next.js) — same structure, copy,
 * links and breakpoints; the account area replaces the marketing "Access portals / Get started"
 * buttons once the learner is signed in. Styles live in edulage-brand/scss/_chrome.scss.
 */

const EL_MAIN_LINKS = [
  ['Programmes', '/programmes'],
  ['Institutions', '/institutions'],
];

const EL_CATALOGUE_LINKS = [
  ['Open Education Centers', '/open-education-centers'],
  ['For institutions', '/for-institutions'],
  ['About', '/about'],
];

const EL_UTILITY_LINKS = [
  ['GOE Initiative', '/goe'],
  ['Global Network', '/institutions'],
  ['Help & Support', '/help'],
  ['Verify a credential', '/verify'],
];

const EL_STUDY_TYPE_LINKS = [
  ["Bachelor's degrees", '/programmes?level=Undergraduate'],
  ["Master's degrees", '/programmes?level=Postgraduate'],
  ['Doctoral / PhD', '/programmes?level=Doctoral'],
  ['Professional diplomas & certificates', '/programmes?level=Professional'],
  ['Fully online', '/programmes?mode=Fully+online'],
  ['Online + OEC exams', '/programmes?mode=Online+%2B+OEC+exams'],
];

const EL_FOOTER_COLUMNS = [
  ['Explore', [
    ['Browse programmes', '/programmes'],
    ['Featured institutions', '/institutions'],
    ['Study options', '/study-types'],
    ['Find an OEC', '/open-education-centers'],
  ]],
  ['Institutions', [
    ['Why EduLage', '/for-institutions'],
    ['Readiness requirements', '/for-institutions'],
    ['Apply to join', '/for-institutions'],
    ['Course production', '/for-institutions'],
  ]],
  ['Access & support', [
    ['Open Education Centers', '/open-education-centers'],
    ['OEC standards', '/open-education-centers'],
    ['Learner support', '/help'],
    ['Verify a credential', '/verify'],
  ]],
  ['Global network', [
    ['GOE Initiative', '/goe'],
    ['Countries', '/institutions'],
    ['Governments & partners', '/goe'],
    ['Institutional network', '/institutions'],
  ]],
  ['About EduLage', [
    ['Our model', '/about'],
    ['Quality and trust', '/quality-and-trust'],
    ['Governance', '/about'],
    ['Contact', '/contact'],
  ]],
];

const elConfig = () => {
  const cfg = getConfig();
  const site = (cfg.EDULAGE_SITE_URL || 'https://edulage.org').replace(/\/$/, '');
  const lms = (cfg.LMS_BASE_URL || '').replace(/\/$/, '');
  const brand = (cfg.EDULAGE_BRAND_URL || '/brand').replace(/\/$/, '');
  return {
    site,
    lms,
    brand,
    tagline: cfg.EDULAGE_TAGLINE || 'The Global Education Village',
    copyright: cfg.EDULAGE_COPYRIGHT || 'EduLage.org',
    logo: `${brand}/images/edulage-logo.png`,
    logoWhite: `${brand}/images/edulage-logo-white.png`,
    dashboard: cfg.LEARNER_DASHBOARD_URL || `${lms}/dashboard`,
    login: cfg.LOGIN_URL || `${lms}/login`,
    logout: cfg.LOGOUT_URL || `${lms}/logout`,
    account: cfg.ACCOUNT_SETTINGS_URL || `${lms}/account/settings`,
    profile: cfg.ACCOUNT_PROFILE_URL || lms,
    studio: cfg.STUDIO_BASE_URL || '',
    support: cfg.SUPPORT_URL || `${site}/help`,
  };
};

const ElIcon = ({ size = 24, children, ...rest }) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
    {...rest}
  >
    {children}
  </svg>
);
const ElSearchIcon = (p) => <ElIcon {...p}><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></ElIcon>;
const ElMenuIcon = (p) => <ElIcon {...p}><line x1="4" x2="20" y1="12" y2="12" /><line x1="4" x2="20" y1="6" y2="6" /><line x1="4" x2="20" y1="18" y2="18" /></ElIcon>;
const ElCloseIcon = (p) => <ElIcon {...p}><path d="M18 6 6 18" /><path d="m6 6 12 12" /></ElIcon>;
const ElChevronDown = (p) => <ElIcon {...p}><path d="m6 9 6 6 6-6" /></ElIcon>;

const elInitials = (user) => {
  const source = (user && (user.name || user.username)) || '';
  const parts = source.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) { return '?'; }
  return (parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

const ElButton = ({ href, variant = 'primary', compact = false, className = '', children, ...rest }) => {
  const classes = `el-btn el-btn--${variant}${compact ? ' el-btn--compact' : ''} ${className}`.trim();
  if (href) { return <a href={href} className={classes} {...rest}>{children}</a>; }
  return <button type="button" className={classes} {...rest}>{children}</button>;
};

/** Sign-in state aware account controls (desktop). */
const ElAccountMenu = ({ user, c, open, setOpen }) => {
  if (!user) {
    return (
      <>
        <ElButton href={c.login} variant="secondary" compact>Sign in</ElButton>
        <ElButton href={`${c.site}/programmes`} compact>Explore programmes</ElButton>
      </>
    );
  }
  const isStaff = Boolean(user.administrator) || (Array.isArray(user.roles) && user.roles.length > 0);
  return (
    <>
      <ElButton href={c.dashboard} variant="secondary" compact>My learning</ElButton>
      <div className="el-header__dropdown-wrap el-header__user">
        <ElButton
          variant="primary"
          compact
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls="el-account-menu"
          onClick={() => setOpen((v) => !v)}
        >
          <span className="el-avatar">{elInitials(user)}</span>
          <span>{user.name ? user.name.split(' ')[0] : user.username}</span>
          <ElChevronDown size={15} />
        </ElButton>
        {open && (
          <div id="el-account-menu" role="menu" className="el-header__menu el-header__menu--right">
            <div className="el-header__menu-user">
              <strong>{user.name || user.username}</strong>
              <span>{user.email}</span>
            </div>
            <a role="menuitem" href={c.dashboard}>My learning</a>
            <a role="menuitem" href={c.site}>EduLage home</a>
            <a role="menuitem" href={`${c.profile}/u/${user.username}`}>Profile</a>
            <a role="menuitem" href={c.account}>Account settings</a>
            {isStaff && c.studio && <a role="menuitem" href={c.studio}>Studio</a>}
            <a role="menuitem" href={c.support}>Help & support</a>
            <div className="el-header__menu-foot">
              <a role="menuitem" href={c.logout}>Sign out</a>
            </div>
          </div>
        )}
      </div>
    </>
  );
};

/**
 * Main site header. `course` (optional): { org, title, href } renders the learning context strip.
 */
const EdulageHeader = ({ course }) => {
  const authenticatedUser = getAuthenticatedUser();
  const c = elConfig();
  const [open, setOpen] = useState(false);
  const [studyOpen, setStudyOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const headerRef = useRef(null);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setStudyOpen(false); setSearchOpen(false); setOpen(false); setUserOpen(false);
      }
    };
    const handlePointerDown = (event) => {
      if (headerRef.current && !headerRef.current.contains(event.target)) {
        setStudyOpen(false); setSearchOpen(false); setUserOpen(false);
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('pointerdown', handlePointerDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('pointerdown', handlePointerDown);
    };
  }, []);

  useEffect(() => {
    if (!open) { return undefined; }
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previousOverflow; };
  }, [open]);

  const showSearch = useCallback(() => {
    setSearchOpen((v) => !v); setStudyOpen(false); setOpen(false); setUserOpen(false);
  }, []);

  const homeHref = c.site;
  const siteLink = (href) => `${c.site}${href}`;

  return (
    <>
      <a href="#main-content" className="el-sr-only">Skip to main content</a>
      <div className="el-utility">
        <div className="el-container">
          <span>{c.tagline}</span>
          <div className="el-utility__links">
            {EL_UTILITY_LINKS.map(([label, href]) => (
              <a key={href + label} href={siteLink(href)}>{label}</a>
            ))}
          </div>
        </div>
      </div>
      <header ref={headerRef} className="el-header">
        <div className="el-container el-header__bar">
          <a href={homeHref} aria-label="EduLage home" className="el-header__logo">
            <img src={c.logo} alt="EduLage" width="150" height="54" />
          </a>
          <nav className="el-header__nav" aria-label="Main navigation">
            {EL_MAIN_LINKS.map(([label, href]) => (
              <a key={href} href={siteLink(href)} className="el-header__link">{label}</a>
            ))}
            <div className="el-header__dropdown-wrap">
              <button
                type="button"
                className="el-header__menu-toggle"
                aria-expanded={studyOpen}
                aria-haspopup="menu"
                aria-controls="study-types-menu"
                onClick={() => { setStudyOpen((v) => !v); setSearchOpen(false); setUserOpen(false); }}
              >
                Study types
                <ElChevronDown size={15} />
              </button>
              {studyOpen && (
                <div id="study-types-menu" role="menu" className="el-header__menu">
                  {EL_STUDY_TYPE_LINKS.map(([label, href]) => (
                    <a role="menuitem" key={href} href={siteLink(href)}>{label}</a>
                  ))}
                  <div className="el-header__menu-foot">
                    <a role="menuitem" href={siteLink('/study-types')}>Compare all study types <span aria-hidden>→</span></a>
                  </div>
                </div>
              )}
            </div>
            {EL_CATALOGUE_LINKS.map(([label, href]) => (
              <a key={href} href={siteLink(href)} className="el-header__link">{label}</a>
            ))}
          </nav>
          <div className="el-header__actions">
            <button
              type="button"
              aria-label="Search programmes"
              aria-expanded={searchOpen}
              aria-controls="header-search-panel"
              onClick={showSearch}
              className="el-header__icon-btn"
            >
              <ElSearchIcon size={19} />
            </button>
            <ElAccountMenu user={authenticatedUser} c={c} open={userOpen} setOpen={setUserOpen} />
          </div>
          <button
            type="button"
            className="el-header__burger"
            aria-label="Open navigation"
            aria-expanded={open}
            onClick={() => setOpen(true)}
          >
            <ElMenuIcon size={24} />
          </button>
        </div>
        {course && (course.title || course.org) && (
          <div className="el-header__course">
            <div className="el-container">
              <div>
                {course.org && <span className="el-header__course-org">{course.org}</span>}
                {course.title && (
                  course.href
                    ? <a className="el-header__course-title" href={course.href}>{course.title}</a>
                    : <span className="el-header__course-title">{course.title}</span>
                )}
              </div>
              <a className="el-header__course-back" href={c.dashboard}>← My learning</a>
            </div>
          </div>
        )}
        {searchOpen && (
          <div id="header-search-panel" className="el-header__search">
            <div className="el-container">
              <form action={siteLink('/programmes')} method="get">
                <label htmlFor="header-search" className="el-sr-only">Search programmes</label>
                <input
                  id="header-search"
                  name="q"
                  autoFocus
                  placeholder="Search programmes, disciplines or institutions"
                />
                <ElButton type="submit">Search</ElButton>
              </form>
            </div>
          </div>
        )}
        {open && (
          <div className="el-drawer">
            <div className="el-drawer__top">
              <a href={homeHref} onClick={() => setOpen(false)}>
                <img src={c.logo} alt="EduLage" width="150" height="54" />
              </a>
              <button type="button" onClick={() => setOpen(false)} aria-label="Close navigation" className="el-drawer__close">
                <ElCloseIcon size={25} />
              </button>
            </div>
            <nav className="el-drawer__nav" aria-label="Mobile navigation">
              {authenticatedUser && (
                <>
                  <a href={c.dashboard} className="el-drawer__primary">My learning</a>
                  <a href={c.site} className="el-drawer__primary">EduLage home</a>
                  <a href={`${c.profile}/u/${authenticatedUser.username}`} className="el-drawer__primary">Profile</a>
                  <a href={c.account} className="el-drawer__primary">Account settings</a>
                </>
              )}
              {[...EL_MAIN_LINKS, ...EL_CATALOGUE_LINKS].map(([label, href]) => (
                <a key={`${label}-${href}`} href={siteLink(href)} className="el-drawer__primary">{label}</a>
              ))}
              <p className="el-kicker">Study options</p>
              {EL_STUDY_TYPE_LINKS.slice(0, 4).map(([label, href]) => (
                <a key={href} href={siteLink(href)}>{label}</a>
              ))}
              <p className="el-kicker">More</p>
              {EL_UTILITY_LINKS.map(([label, href]) => (
                <a key={`${label}-${href}`} href={siteLink(href)}>{label}</a>
              ))}
              <button type="button" onClick={showSearch}>Search programmes</button>
            </nav>
            <div className="el-drawer__foot">
              {authenticatedUser ? (
                <>
                  <ElButton href={c.logout} variant="secondary">Sign out</ElButton>
                  <ElButton href={c.dashboard}>My learning</ElButton>
                </>
              ) : (
                <>
                  <ElButton href={c.login} variant="secondary">Sign in</ElButton>
                  <ElButton href={`${c.site}/programmes`}>Explore programmes</ElButton>
                </>
              )}
            </div>
          </div>
        )}
      </header>
    </>
  );
};

/** Learning MFE header: receives courseOrg/courseNumber/courseTitle via slot pluginProps. */
const EdulageLearningHeader = ({ courseOrg, courseNumber, courseTitle }) => {
  const c = elConfig();
  const match = window.location.pathname.match(/(course-v1:[^/]+)/);
  const href = match ? `${c.lms}/courses/${match[1]}/course/` : undefined;
  const org = [courseOrg, courseNumber].filter(Boolean).join(' · ');
  const course = { org, title: courseTitle, href };
  return <EdulageHeader course={course} />;
};

const ElFooterLegal = ({ c }) => (
  <div className="el-footer__legal">
    <p>© {new Date().getFullYear()} {c.copyright}. All rights reserved.</p>
    <div>
      <a href={`${c.site}/privacy`}>Privacy</a>
      <a href={`${c.site}/terms`}>Terms</a>
      <a href={`${c.site}/accessibility`}>Accessibility</a>
      <a href={`${c.site}/data-protection`}>Data protection</a>
      <a href={`${c.site}/contact`}>Contact</a>
      <span aria-label="Current site language">English (default)</span>
    </div>
  </div>
);

const EdulageFooter = () => {
  const c = elConfig();
  return (
    <footer className="el-footer" role="contentinfo">
      <div className="el-container">
        <div className="el-footer__main">
          <div className="el-footer__lead">
            <div>
              <img src={c.logoWhite} alt="EduLage" width="150" height="54" className="el-footer__logo" />
              <p className="el-footer__statement">
                {c.tagline}—connecting learners to quality open and online education from reputable
                tertiary institutions worldwide.
              </p>
            </div>
            <div className="el-footer__help">
              <p className="el-footer__help-title">Need help finding the right pathway?</p>
              <p className="el-footer__help-text">
                Explore programmes, participating institutions and supported access options.
              </p>
              <div className="el-footer__help-actions">
                <a href={`${c.site}/programmes`} className="el-footer__help-primary">Explore programmes</a>
                <a href={`${c.site}/help`} className="el-footer__help-secondary">Help & support</a>
              </div>
            </div>
          </div>
          <div className="el-footer__columns">
            {EL_FOOTER_COLUMNS.map(([title, items]) => (
              <div key={title}>
                <h3>{title}</h3>
                <ul>
                  {items.map(([label, href]) => (
                    <li key={label}><a href={`${c.site}${href}`}>{label}</a></li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
        <ElFooterLegal c={c} />
      </div>
    </footer>
  );
};

/** Studio (authoring MFE): compact legal bar only — authors don't need marketing navigation. */
const EdulageStudioFooter = () => {
  const c = elConfig();
  return (
    <footer className="el-footer el-footer--compact" role="contentinfo">
      <div className="el-container">
        <nav className="el-footer__legal" aria-label="EduLage">
          <a href={c.site}>EduLage home</a>
          <a href={c.dashboard}>My learning</a>
          <a href={`${c.site}/for-institutions`}>For institutions</a>
          <a href={`${c.site}/help`}>Help & support</a>
        </nav>
        <ElFooterLegal c={c} />
      </div>
    </footer>
  );
};

/**
 * Learner dashboard — "My Learning" empty state (no_courses_view slot).
 * Discovery stays on edulage.org; the LMS only points back to it.
 */
const EdulageNoCoursesView = () => {
  const c = elConfig();
  return (
    <section className="el-empty" aria-labelledby="el-empty-title">
      <p className="el-eyebrow">My learning</p>
      <h2 id="el-empty-title" className="el-empty__title">You are not enrolled in any programme yet</h2>
      <p className="el-empty__text">
        Enrolled programmes and courses appear here once an institution has approved your
        admission. Browse the EduLage catalogue to find accredited programmes from
        participating tertiary institutions.
      </p>
      <div className="el-empty__actions">
        <ElButton href={`${c.site}/programmes`}>Explore programmes</ElButton>
        <ElButton href={`${c.site}/help`} variant="secondary">Help &amp; support</ElButton>
      </div>
    </section>
  );
};

/** Learner dashboard — right-hand sidebar (widget_sidebar slot). */
const EdulageDashboardSidebar = () => {
  const c = elConfig();
  const items = [
    ['Explore more programmes', `${c.site}/programmes`, 'Degrees, professional programmes and short courses from participating institutions.'],
    ['Find an Open Education Center', `${c.site}/open-education-centers`, 'Local study support, supervised examinations and internet access.'],
    ['Verify a credential', `${c.site}/verify`, 'Credentials are issued by institutions and recorded and verified by EduLage.'],
    ['Learner support', c.support, 'Help with access, enrolment and your learning schedule.'],
  ];
  return (
    <aside className="el-side" aria-label="EduLage services">
      <p className="el-eyebrow">EduLage</p>
      <ul className="el-side__list">
        {items.map(([label, href, text]) => (
          <li key={label} className="el-side__item">
            <a href={href} className="el-side__link">{label} <span aria-hidden="true">→</span></a>
            <p className="el-side__text">{text}</p>
          </li>
        ))}
      </ul>
    </aside>
  );
};
