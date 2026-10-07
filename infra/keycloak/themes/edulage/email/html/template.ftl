<#-- EduLage e-mail frame: same card/header/footer as the LMS ACE base_body.html (platform-plugin-edulage). -->
<#macro emailLayout>
<html lang="${locale.language}" dir="${(ltr)?then('ltr','rtl')}">
<body style="margin:0;padding:0;background-color:#f3f6f2;">
<div bgcolor="#f3f6f2" style="margin:0;padding:0;min-width:100%;background-color:#f3f6f2;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f3f6f2" style="background-color:#f3f6f2;">
    <tr><td height="28" style="line-height:1px;font-size:1px;">&nbsp;</td></tr>
    <tr>
      <td align="center" valign="top" style="padding:0 16px;">
        <table role="presentation" align="center" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:600px;background-color:#ffffff;border:1px solid #e0e7e2;border-radius:16px;overflow:hidden;box-shadow:0 18px 45px rgba(6,16,52,0.09);">
          <tr>
            <td bgcolor="#123c36" style="background-color:#123c36;padding:0;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td bgcolor="#102f36" style="background-color:#102f36;padding:9px 32px;font-family:'Inter',Helvetica,Arial,sans-serif;font-size:12px;line-height:18px;color:#cfddd3;letter-spacing:0.02em;">The Global Education Village</td>
                </tr>
                <tr>
                  <td style="padding:22px 32px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td align="left" valign="middle">
                          <a href="https://edulage.org" target="_blank" style="text-decoration:none;">
                            <img src="https://learn.edulage.org/media/brand/edulage-logo-white.png" width="132" height="43" style="display:block;width:132px;height:auto;border:0;" alt="EduLage"/>
                          </a>
                        </td>
                        <td align="right" valign="middle" style="font-family:'Inter',Helvetica,Arial,sans-serif;font-size:13px;line-height:20px;white-space:nowrap;padding-left:16px;">
                          <a href="https://edulage.org/programmes" target="_blank" style="color:#ffffff;text-decoration:none;font-weight:600;">Programmes</a>
                          <span style="color:#536c62;">&nbsp;&nbsp;|&nbsp;&nbsp;</span>
                          <a href="https://learn.edulage.org/dashboard" target="_blank" style="color:#ffffff;text-decoration:none;font-weight:600;">My learning</a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr><td height="4" bgcolor="#08705f" style="background-color:#08705f;line-height:1px;font-size:1px;">&nbsp;</td></tr>
              </table>
            </td>
          </tr>
          <tr>
            <td bgcolor="#ffffff" style="padding:36px 40px 40px 40px;background-color:#ffffff;font-family:'Inter',Helvetica,Arial,sans-serif;font-size:16px;line-height:26px;color:#536c62;">
              <#nested>
            </td>
          </tr>
          <tr>
            <td bgcolor="#f3f6f2" style="background-color:#f3f6f2;border-top:1px solid #e0e7e2;padding:24px 40px 28px 40px;font-family:'Inter',Helvetica,Arial,sans-serif;font-size:13px;line-height:20px;color:#536c62;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="padding-bottom:12px;">
                    <a href="https://edulage.org/programmes" target="_blank" style="color:#123c36;text-decoration:none;font-weight:600;">Programmes</a>
                    <span style="color:#7b8f86;">&nbsp;·&nbsp;</span>
                    <a href="https://edulage.org/institutions" target="_blank" style="color:#123c36;text-decoration:none;font-weight:600;">Institutions</a>
                    <span style="color:#7b8f86;">&nbsp;·&nbsp;</span>
                    <a href="https://learn.edulage.org/dashboard" target="_blank" style="color:#123c36;text-decoration:none;font-weight:600;">My learning</a>
                    <span style="color:#7b8f86;">&nbsp;·&nbsp;</span>
                    <a href="https://edulage.org/help" target="_blank" style="color:#123c36;text-decoration:none;font-weight:600;">Help centre</a>
                  </td>
                </tr>
                <tr><td style="padding-bottom:12px;color:#536c62;">Need a hand? Write to support@edulage.org and our learner support team will help.</td></tr>
                <tr>
                  <td style="font-size:12px;line-height:18px;color:#7b8f86;">
                    &copy; ${.now?string("yyyy")} EduLage &mdash; The Global Education Village.
                    <a href="https://edulage.org/privacy" target="_blank" style="color:#7b8f86;text-decoration:underline;">Privacy</a>
                    &nbsp;·&nbsp;
                    <a href="https://edulage.org/terms" target="_blank" style="color:#7b8f86;text-decoration:underline;">Terms</a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    <tr><td height="32" style="line-height:1px;font-size:1px;">&nbsp;</td></tr>
  </table>
</div>
</body>
</html>
</#macro>
