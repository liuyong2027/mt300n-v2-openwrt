package main

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestMultiUserLegacyMigration(t *testing.T) {
	r := registryFromLegacy(managedAccount{"guest", "aB3!x7"})
	if e := validateRegistry(r); e != nil {
		t.Fatal(e)
	}
	if primaryAccount(r).Password != "aB3!x7" || !r.Users[0].Admin {
		t.Fatal("legacy account not preserved")
	}
}
func TestMultiUserMutationsAndBoundaries(t *testing.T) {
	r := registryFromLegacy(managedAccount{"guest", "aB3!x7"})
	var e error
	r, e = editManagedUser(r, managedUserEdit{"", "reader", "rE4@d1", false})
	if e != nil {
		t.Fatal(e)
	}
	updated, e := editManagedUser(r, managedUserEdit{"reader", "visitor", "", false})
	if e != nil || updated.Users[1].Password != "rE4@d1" || r.Users[1].Username != "reader" {
		t.Fatal("edit or copy semantics")
	}
	for _, bad := range []managedUserEdit{{"", "guest", "nE8@q2", true}, {"", "anonymous", "nE8@q2", false}, {"", "short", "12345", false}, {"guest", "guest", "", false}, {"missing", "other", "123456", false}} {
		if _, e := editManagedUser(r, bad); e == nil {
			t.Fatal("accepted invalid edit")
		}
	}
	if _, e := deleteManagedUser(r, "guest"); e == nil {
		t.Fatal("deleted primary")
	}
	if out, e := deleteManagedUser(r, "reader"); e != nil || len(out.Users) != 1 {
		t.Fatal("delete failed")
	}
	if _, e := editManagedUser(r, managedUserEdit{"guest", "owner", "", true}); e != nil {
		t.Fatal("rename primary failed")
	}
	for i := 2; i < maxManagedUsers; i++ {
		name := "usr" + strings.Repeat("x", i)
		r, e = editManagedUser(r, managedUserEdit{"", name, "123456", false})
		if e != nil {
			t.Fatal(e)
		}
	}
	if _, e := editManagedUser(r, managedUserEdit{"", "overflow", "123456", true}); e == nil {
		t.Fatal("limit exceeded")
	}
}
func TestMultiUserPermissionPayloadAndPrivacy(t *testing.T) {
	u := managedUser{"reader", "rE4@d1", false, false}
	for _, tc := range []struct{ userRW, sourceRO, want bool }{{false, false, false}, {true, false, true}, {true, true, false}} {
		u.ReadWrite = tc.userRW
		var p struct {
			Data struct {
				Permissions map[string]bool
				Scopes      []struct{ Permissions map[string]bool }
			}
		}
		json.Unmarshal(quantumUserPayload(u, tc.sourceRO), &p)
		if p.Data.Permissions["admin"] || p.Data.Permissions["api"] {
			t.Fatal("normal user elevated")
		}
		for _, k := range []string{"modify", "create", "delete"} {
			if p.Data.Scopes[0].Permissions[k] != tc.want {
				t.Fatal("file permission mismatch")
			}
		}
		if !p.Data.Scopes[0].Permissions["view"] || !p.Data.Scopes[0].Permissions["download"] {
			t.Fatal("cannot read")
		}
	}
	b, _ := json.Marshal(publicManagedUsers(registryFromLegacy(managedAccount{"guest", "aB3!x7"})))
	if strings.Contains(string(b), "aB3!x7") || strings.Contains(string(b), "password") {
		t.Fatal("public response leaks password")
	}
}
